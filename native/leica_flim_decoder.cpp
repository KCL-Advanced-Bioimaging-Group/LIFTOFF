#include "leica_flim_decoder.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr uint32_t API_VERSION = 6;
constexpr const char* VERSION = "3.3.1";
constexpr uint8_t CODE_ORDER[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5,
                                    11, 4, 12, 3, 13, 2, 14, 1, 15};

uint32_t read_u32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

uint64_t read_u64(const uint8_t* p) {
    return static_cast<uint64_t>(read_u32(p)) |
           (static_cast<uint64_t>(read_u32(p + 4)) << 32);
}

uint32_t reverse_bits(uint32_t value, uint32_t width) {
    uint32_t result = 0;
    for (uint32_t i = 0; i < width; ++i) {
        result = (result << 1) | (value & 1u);
        value >>= 1;
    }
    return result;
}

class BitReader {
public:
    BitReader(const uint8_t* data, uint64_t bytes, uint64_t start, uint64_t limit)
        : data_(data), bytes_(bytes), pos_(start), limit_(std::min(limit, bytes * 8)) {
        if (start > limit_) throw std::runtime_error("bit range starts beyond input");
    }

    uint32_t read(uint32_t count) {
        uint32_t value = peek(count);
        if (pos_ + count > limit_) throw std::runtime_error("end of bit range");
        pos_ += count;
        return value;
    }

    uint32_t peek(uint32_t count) const {
        if (count > 24) throw std::runtime_error("invalid buffered bit read");
        const uint32_t available = static_cast<uint32_t>(std::min<uint64_t>(count, limit_ - pos_));
        if (!available) return 0;
        const uint64_t byte = pos_ >> 3;
        const uint32_t shift = static_cast<uint32_t>(pos_ & 7u);
        const uint32_t needed = (shift + available + 7u) >> 3;
        uint64_t buffer = 0;
        for (uint32_t i = 0; i < needed; ++i) {
            if (byte + i >= bytes_) throw std::runtime_error("bit read beyond input");
            buffer |= static_cast<uint64_t>(data_[byte + i]) << (i * 8u);
        }
        const uint64_t mask = (1ull << available) - 1ull;
        return static_cast<uint32_t>((buffer >> shift) & mask);
    }

    uint64_t position() const { return pos_; }
    uint64_t limit() const { return limit_; }

private:
    const uint8_t* data_;
    uint64_t bytes_;
    uint64_t pos_;
    uint64_t limit_;
};

struct HuffmanTable {
    std::vector<int16_t> symbols;
    std::vector<uint8_t> widths;
    uint32_t maximum = 0;
};

HuffmanTable build_huffman(const std::vector<uint8_t>& lengths, bool allow_empty = false) {
    HuffmanTable table;
    for (uint8_t length : lengths) table.maximum = std::max(table.maximum, uint32_t(length));
    if (table.maximum == 0) {
        if (allow_empty) return table;
        throw std::runtime_error("empty Huffman alphabet");
    }
    std::vector<uint32_t> counts(table.maximum + 1, 0), next(table.maximum + 1, 0);
    for (uint8_t length : lengths) if (length) ++counts[length];
    uint32_t code = 0;
    for (uint32_t bits = 1; bits <= table.maximum; ++bits) {
        code = (code + counts[bits - 1]) << 1;
        next[bits] = code;
    }
    const size_t size = size_t(1) << table.maximum;
    table.symbols.assign(size, -1);
    table.widths.assign(size, 0);
    for (uint32_t symbol = 0; symbol < lengths.size(); ++symbol) {
        const uint32_t length = lengths[symbol];
        if (!length) continue;
        const uint32_t reversed = reverse_bits(next[length]++, length);
        for (size_t index = reversed; index < size; index += size_t(1) << length) {
            table.symbols[index] = static_cast<int16_t>(symbol);
            table.widths[index] = static_cast<uint8_t>(length);
        }
    }
    return table;
}

int decode_symbol(BitReader& reader, const HuffmanTable& table) {
    if (!table.maximum) throw std::runtime_error("empty Huffman table used");
    const uint32_t index = reader.peek(table.maximum);
    const uint8_t width = table.widths[index];
    if (!width) throw std::runtime_error("invalid Huffman code");
    reader.read(width);
    return table.symbols[index];
}

HuffmanTable read_dynamic_literal_table(BitReader& reader) {
    const uint32_t hlit = reader.read(5) + 257;
    const uint32_t hdist = reader.read(5) + 1;
    const uint32_t hclen = reader.read(4) + 4;
    std::vector<uint8_t> code_lengths(19, 0);
    for (uint32_t i = 0; i < hclen; ++i) code_lengths[CODE_ORDER[i]] = uint8_t(reader.read(3));
    const HuffmanTable code_table = build_huffman(code_lengths);
    std::vector<uint8_t> result;
    result.reserve(hlit + hdist);
    while (result.size() < hlit + hdist) {
        const int symbol = decode_symbol(reader, code_table);
        if (symbol <= 15) {
            result.push_back(static_cast<uint8_t>(symbol));
        } else if (symbol == 16) {
            if (result.empty()) throw std::runtime_error("repeat without previous code");
            const uint32_t count = reader.read(2) + 3;
            result.insert(result.end(), count, result.back());
        } else if (symbol == 17) {
            result.insert(result.end(), reader.read(3) + 3, 0);
        } else if (symbol == 18) {
            result.insert(result.end(), reader.read(7) + 11, 0);
        } else {
            throw std::runtime_error("invalid code-length symbol");
        }
        if (result.size() > hlit + hdist) throw std::runtime_error("code-length repeat overflow");
    }
    HuffmanTable literals = build_huffman(std::vector<uint8_t>(result.begin(), result.begin() + hlit));
    (void)build_huffman(std::vector<uint8_t>(result.begin() + hlit, result.end()), true);
    return literals;
}

struct RowJob {
    uint32_t line;
    uint64_t start_bit;
    uint64_t end_bit;
    std::shared_ptr<const HuffmanTable> literals;
};

struct PreparedBlock {
    const uint8_t* block = nullptr;
    uint64_t block_size = 0;
    const uint8_t* stream = nullptr;
    uint64_t stream_size = 0;
    uint64_t expected_rows = 0;
    std::vector<RowJob> jobs;
};

uint32_t marker_bit(uint8_t token) {
    const uint32_t shift = (token & 7u) * 4;
    switch (token & 0xf8u) {
        case 0xA8: return 1u << shift;
        case 0xA0: return 2u << shift;
        case 0xB0: return 4u << shift;
        case 0xB8: return 8u << shift;
        default: return 0u;
    }
}

bool is_class_marker(uint8_t token) {
    return token >= 0xa0 && token <= 0xbf;
}

void set_error(char* target, uint32_t capacity, const std::string& message) {
    if (!target || capacity == 0) return;
    const size_t count = std::min<size_t>(capacity - 1, message.size());
    std::memcpy(target, message.data(), count);
    target[count] = '\0';
}

std::unique_ptr<PreparedBlock> prepare_block(const uint8_t* block, uint64_t block_size) {
    if (!block) throw std::runtime_error("null compressed block pointer");
    if (block_size < 64) throw std::runtime_error("compressed block is shorter than its header");
    auto prepared = std::make_unique<PreparedBlock>();
    prepared->block = block;
    prepared->block_size = block_size;
    const uint64_t stream_start = read_u64(block + 8);
    prepared->stream_size = read_u64(block + 16);
    const uint64_t table_size = read_u64(block + 24);
    prepared->expected_rows = read_u64(block + 40);
    if (stream_start > block_size || prepared->stream_size > block_size - stream_start)
        throw std::runtime_error("compressed stream range is invalid");
    const uint64_t table_start = stream_start + prepared->stream_size;
    if (table_start > block_size || table_size > block_size - table_start || table_size % 4)
        throw std::runtime_error("descriptor table range is invalid");
    prepared->stream = block + stream_start;
    const uint8_t* table_data = block + table_start;
    const size_t descriptor_count = static_cast<size_t>(table_size / 4);
    if (prepared->expected_rows > descriptor_count || prepared->expected_rows > UINT32_MAX)
        throw std::runtime_error("compressed row count exceeds descriptor capacity");
    std::vector<uint32_t> lengths(descriptor_count), flags(descriptor_count);
    for (size_t i = 0; i < descriptor_count; ++i) {
        const uint32_t value = read_u32(table_data + i * 4);
        lengths[i] = value & 0x3fffffffu;
        flags[i] = (value >> 16) & 0xc000u;
    }

    prepared->jobs.reserve(static_cast<size_t>(prepared->expected_rows));
    uint64_t cursor = 0;
    uint32_t line = 0;
    for (size_t base = 0, group = 0; base < descriptor_count; ++group) {
        if (flags[base] != 0) throw std::runtime_error("descriptor group starts with a nonzero flag");
        size_t next = base + 1;
        while (next < descriptor_count && flags[next] != 0) ++next;
        if (next - base < 3) throw std::runtime_error("descriptor group has no row payload");
        uint64_t group_bits = 0;
        for (size_t i = base; i < next; ++i) group_bits += lengths[i];
        if (cursor + group_bits > prepared->stream_size * 8)
            throw std::runtime_error("descriptor bits exceed stream");
        BitReader reader(prepared->stream, prepared->stream_size, cursor, cursor + group_bits);
        reader.read(8); reader.read(8);
        reader.read(1);
        if (reader.read(2) != 2) throw std::runtime_error("expected dynamic Huffman block");
        auto literals = std::make_shared<HuffmanTable>(read_dynamic_literal_table(reader));
        const uint64_t header_bits = reader.position() - cursor - 16;
        if (header_bits != lengths[base + 1]) throw std::runtime_error("dynamic header length mismatch");
        if (flags[base + 1] != 0xc000u)
            throw std::runtime_error("unexpected descriptor control flags");
        uint64_t row_start = reader.position();
        for (size_t rel = base + 2; rel < next; ++rel) {
            const uint64_t row_end = row_start + lengths[rel];
            prepared->jobs.push_back(RowJob{line++, row_start, row_end, literals});
            row_start = row_end;
        }
        if (row_start != cursor + group_bits) throw std::runtime_error("group bit accounting mismatch");
        cursor += group_bits;
        base = next;
    }
    if (prepared->jobs.size() != prepared->expected_rows)
        throw std::runtime_error("decoded row count differs from block header");
    return prepared;
}

} // namespace

extern "C" {

uint32_t leica_decoder_api_version(void) { return API_VERSION; }
const char* leica_decoder_version(void) { return VERSION; }
uint32_t leica_recommended_threads(void) {
    const uint32_t available = std::max(1u, std::thread::hardware_concurrency());
    return std::min(available, 16u);
}

int leica_prepare_block(const uint8_t* block, uint64_t block_size,
                        void** decoder_context, uint32_t* encoded_rows,
                        char* error, uint32_t error_capacity) {
    try {
        if (!decoder_context || !encoded_rows) throw std::runtime_error("null output pointer");
        auto prepared = prepare_block(block, block_size);
        if (prepared->expected_rows > UINT32_MAX) throw std::runtime_error("encoded row count is too large");
        *encoded_rows = static_cast<uint32_t>(prepared->expected_rows);
        *decoder_context = prepared.release();
        return 0;
    } catch (const std::exception& exc) {
        set_error(error, error_capacity, exc.what());
        return -1;
    } catch (...) {
        set_error(error, error_capacity, "unknown native prepare error");
        return -2;
    }
}

void leica_release_block(void* decoder_context) {
    delete static_cast<PreparedBlock*>(decoder_context);
}

int leica_decode_row_range(void* decoder_context,
                           uint32_t first_row, uint32_t row_count,
                           uint32_t width, uint32_t height, uint32_t bins,
                           uint32_t period_bins, const int32_t* arrival_bins,
                           uint32_t arrival_bins_count, uint32_t line_repetitions,
                           uint32_t row_model, uint32_t event_flag_mask, uint32_t thread_count,
                           void* output_cube, uint64_t output_bytes,
                           leica_progress_callback progress, void* progress_data,
                           const volatile uint32_t* cancel,
                           leica_decode_result* result, char* error,
                           uint32_t error_capacity) {
    const auto started = std::chrono::steady_clock::now();
    try {
        auto* prepared = static_cast<PreparedBlock*>(decoder_context);
        if (!prepared || !output_cube || !result) throw std::runtime_error("null required pointer");
        if (!width || !height || !bins || !period_bins || !row_count || !line_repetitions)
            throw std::runtime_error("zero dimension, period, or row count");
        if (event_flag_mask == 0)
            throw std::runtime_error("invalid compressed event flag mask");
        if (row_model > 1) throw std::runtime_error("unknown repetition row model");
        if (first_row > prepared->jobs.size() || row_count > prepared->jobs.size() - first_row)
            throw std::runtime_error("requested row range is outside the encoded block");
        const uint64_t cells = uint64_t(width) * height * bins;
        if (cells > UINT64_MAX / sizeof(uint32_t) || output_bytes < cells * sizeof(uint32_t))
            throw std::runtime_error("output cube is too small");
        auto* output = static_cast<uint32_t*>(output_cube);
        std::fill(output, output + cells, 0u);

        const uint32_t workers_count = std::max(
            1u, std::min(thread_count ? thread_count : leica_recommended_threads(), row_count));
        std::atomic<size_t> next_job{0};
        std::atomic<uint32_t> completed{0};
        std::atomic<uint64_t> photons{0}, overflows{0};
        std::atomic<bool> failed{false};
        std::vector<std::mutex> row_mutexes(height);
        std::mutex error_mutex;
        std::string worker_error;

        auto worker = [&]() {
            std::vector<uint32_t> row_counts(size_t(bins) * width);
            while (!failed.load(std::memory_order_relaxed)) {
                if (cancel && *cancel) break;
                const size_t relative = next_job.fetch_add(1);
                if (relative >= row_count) break;
                const RowJob& job = prepared->jobs[first_row + relative];
                std::fill(row_counts.begin(), row_counts.end(), 0u);
                uint32_t x = 0, arrival = 0;
                uint8_t marker = 0, high = 0;
                bool first = true, pending_high = false;
                uint64_t local_photons = 0, local_overflow = 0;
                try {
                    BitReader reader(prepared->stream, prepared->stream_size,
                                     job.start_bit, job.end_bit);
                    while (reader.position() < reader.limit()) {
                        const int decoded = decode_symbol(reader, *job.literals);
                        if (decoded == 256) continue;
                        if (decoded < 0 || decoded > 255)
                            throw std::runtime_error("row contains length symbol");
                        const uint8_t token = static_cast<uint8_t>(decoded);
                        if (token >= 0x81 && token <= 0x9f) {
                            x += token & 0x1f; marker = 0; pending_high = false; continue;
                        }
                        if (is_class_marker(token)) {
                            marker = token; arrival = 0; first = true; pending_high = false; continue;
                        }
                        if (token >= 0xc0) { high = token; pending_high = true; continue; }
                        if (token < 0x80 && marker) {
                            uint32_t delta = token;
                            if (pending_high) delta |= uint32_t(high & 0x3f) << 7;
                            pending_high = false;
                            arrival = first ? delta : arrival + delta;
                            first = false;
                            if (x < width && (event_flag_mask & marker_bit(marker))) {
                                if (arrival_bins && (arrival >= arrival_bins_count || arrival_bins[arrival] < 0)) {
                                    ++local_overflow;
                                    continue;
                                }
                                const uint32_t bin = arrival_bins ? static_cast<uint32_t>(arrival_bins[arrival]) : std::min(
                                    bins - 1, uint32_t(uint64_t(arrival) * bins / period_bins));
                                if (bin >= bins) throw std::runtime_error("invalid calibrated bin mapping");
                                ++row_counts[size_t(bin) * width + x];
                                ++local_photons;
                                if (!arrival_bins && arrival >= period_bins) ++local_overflow;
                            }
                            continue;
                        }
                        marker = 0; pending_high = false;
                    }
                    if (reader.position() != job.end_bit)
                        throw std::runtime_error("row did not consume exact bit length");
                    const uint32_t y = (row_model == 1
                        ? static_cast<uint32_t>((relative % (uint64_t(height) * line_repetitions))
                                                / line_repetitions)
                        : static_cast<uint32_t>(relative % height));
                    {
                        std::lock_guard<std::mutex> lock(row_mutexes[y]);
                        for (uint32_t bin = 0; bin < bins; ++bin) {
                            uint32_t* destination = output + (size_t(bin) * height + y) * width;
                            const uint32_t* source = row_counts.data() + size_t(bin) * width;
                            for (uint32_t column = 0; column < width; ++column) {
                                if (UINT32_MAX - destination[column] < source[column])
                                    throw std::runtime_error("uint32 histogram overflow");
                                destination[column] += source[column];
                            }
                        }
                    }
                    photons.fetch_add(local_photons, std::memory_order_relaxed);
                    overflows.fetch_add(local_overflow, std::memory_order_relaxed);
                    completed.fetch_add(1, std::memory_order_release);
                } catch (const std::exception& exc) {
                    failed.store(true);
                    std::lock_guard<std::mutex> lock(error_mutex);
                    if (worker_error.empty())
                        worker_error = "row " + std::to_string(job.line) + ": " + exc.what();
                }
            }
        };

        std::vector<std::thread> workers;
        workers.reserve(workers_count);
        for (uint32_t i = 0; i < workers_count; ++i) workers.emplace_back(worker);
        uint32_t reported = UINT32_MAX;
        while (completed.load(std::memory_order_acquire) < row_count && !failed.load()) {
            const uint32_t current = completed.load(std::memory_order_acquire);
            if (progress && current != reported) {
                progress(current, row_count, progress_data); reported = current;
            }
            if (cancel && *cancel) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            if (next_job.load() >= row_count && completed.load() + workers_count >= row_count) break;
        }
        for (auto& thread : workers) thread.join();
        if (progress) progress(completed.load(), row_count, progress_data);
        if (failed.load())
            throw std::runtime_error(worker_error.empty() ? "native worker failed" : worker_error);

        result->width = width; result->height = height; result->time_bins = bins;
        result->decoded_rows = completed.load(); result->photon_count = photons.load();
        result->overflow_count = overflows.load(); result->output_bits = 32;
        result->elapsed_seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - started).count();
        if (cancel && *cancel) return 1;
        if (completed.load() != row_count)
            throw std::runtime_error("native workers stopped before row range completed");
        return 0;
    } catch (const std::exception& exc) {
        set_error(error, error_capacity, exc.what());
        return -1;
    } catch (...) {
        set_error(error, error_capacity, "unknown native row-range error");
        return -2;
    }
}

int leica_decode_histogram(const uint8_t* block, uint64_t block_size,
                           uint32_t width, uint32_t height, uint32_t bins,
                           uint32_t period_bins, const int32_t* arrival_bins,
                           uint32_t arrival_bins_count, uint32_t line_repetitions,
                           uint32_t row_model, uint32_t event_flag_mask, uint32_t thread_count,
                           void* output_cube, uint64_t output_bytes,
                           leica_progress_callback progress, void* progress_data,
                           const volatile uint32_t* cancel,
                           leica_decode_result* result, char* error,
                           uint32_t error_capacity) {
    const auto started = std::chrono::steady_clock::now();
    try {
        if (!block || !output_cube || !result) throw std::runtime_error("null required pointer");
        if (block_size < 64) throw std::runtime_error("compressed block is shorter than its header");
        if (!width || !height || !bins || !period_bins || !line_repetitions)
            throw std::runtime_error("zero dimension, period, or repetition count");
        if (event_flag_mask == 0)
            throw std::runtime_error("invalid compressed event flag mask");
        if (row_model > 1) throw std::runtime_error("unknown repetition row model");
        const uint64_t cells = uint64_t(width) * height * bins;
        if (cells > UINT64_MAX / sizeof(uint32_t) || output_bytes < cells * sizeof(uint32_t))
            throw std::runtime_error("output cube is too small");

        const uint64_t stream_start = read_u64(block + 8);
        const uint64_t stream_size = read_u64(block + 16);
        const uint64_t table_size = read_u64(block + 24);
        const uint64_t expected_rows = read_u64(block + 40);
        if (stream_start > block_size || stream_size > block_size - stream_start)
            throw std::runtime_error("compressed stream range is invalid");
        const uint64_t table_start = stream_start + stream_size;
        if (table_start > block_size || table_size > block_size - table_start || table_size % 4)
            throw std::runtime_error("descriptor table range is invalid");

        auto* output = static_cast<uint32_t*>(output_cube);
        std::fill(output, output + cells, 0u);
        const uint8_t* stream = block + stream_start;
        const uint8_t* table_data = block + table_start;
        const size_t descriptor_count = static_cast<size_t>(table_size / 4);
        std::vector<uint32_t> lengths(descriptor_count), flags(descriptor_count);
        for (size_t i = 0; i < descriptor_count; ++i) {
            const uint32_t value = read_u32(table_data + i * 4);
            lengths[i] = value & 0x3fffffffu;
            flags[i] = (value >> 16) & 0xc000u;
        }

        std::vector<RowJob> jobs;
        jobs.reserve(static_cast<size_t>(expected_rows));
        uint64_t cursor = 0;
        uint32_t line = 0;
        for (size_t base = 0, group = 0; base < descriptor_count; ++group) {
            if (flags[base] != 0) throw std::runtime_error("descriptor group starts with a nonzero flag");
            size_t next = base + 1;
            while (next < descriptor_count && flags[next] != 0) ++next;
            if (next - base < 3) throw std::runtime_error("descriptor group has no row payload");
            uint64_t group_bits = 0;
            for (size_t i = base; i < next; ++i) group_bits += lengths[i];
            if (cursor + group_bits > stream_size * 8) throw std::runtime_error("descriptor bits exceed stream");
            BitReader reader(stream, stream_size, cursor, cursor + group_bits);
            reader.read(8); reader.read(8); // zlib wrapper bytes
            reader.read(1);
            if (reader.read(2) != 2) throw std::runtime_error("expected dynamic Huffman block");
            auto literals = std::make_shared<HuffmanTable>(read_dynamic_literal_table(reader));
            const uint64_t header_bits = reader.position() - cursor - 16;
            if (header_bits != lengths[base + 1]) throw std::runtime_error("dynamic header length mismatch");
            if (flags[base] != 0 || flags[base + 1] != 0xc000u)
                throw std::runtime_error("unexpected descriptor control flags");
            uint64_t row_start = reader.position();
            for (size_t rel = base + 2; rel < next; ++rel) {
                const uint64_t row_end = row_start + lengths[rel];
                jobs.push_back(RowJob{line++, row_start, row_end, literals});
                row_start = row_end;
            }
            if (row_start != cursor + group_bits) throw std::runtime_error("group bit accounting mismatch");
            cursor += group_bits;
            base = next;
        }
        if (jobs.size() != expected_rows) throw std::runtime_error("decoded row count differs from block header");

        const uint32_t workers_count = std::max(1u, std::min(thread_count ? thread_count : leica_recommended_threads(),
                                                             static_cast<uint32_t>(jobs.size())));
        std::vector<std::mutex> row_mutexes(height);
        std::atomic<size_t> next_job{0};
        std::atomic<uint32_t> completed{0};
        std::atomic<uint64_t> photons{0}, overflows{0};
        std::atomic<bool> failed{false};
        std::mutex error_mutex;
        std::string worker_error;

        auto worker = [&]() {
            std::vector<uint32_t> row_counts(size_t(bins) * width);
            while (!failed.load(std::memory_order_relaxed)) {
                if (cancel && *cancel) break;
                const size_t index = next_job.fetch_add(1);
                if (index >= jobs.size()) break;
                const RowJob& job = jobs[index];
                std::fill(row_counts.begin(), row_counts.end(), 0u);
                uint32_t x = 0, arrival = 0;
                uint8_t marker = 0, high = 0;
                bool first = true, pending_high = false;
                uint64_t local_photons = 0, local_overflow = 0;
                try {
                    BitReader reader(stream, stream_size, job.start_bit, job.end_bit);
                    while (reader.position() < reader.limit()) {
                        const int decoded = decode_symbol(reader, *job.literals);
                        if (decoded == 256) continue;
                        if (decoded < 0 || decoded > 255)
                            throw std::runtime_error("row contains length symbol");
                        const uint8_t token = static_cast<uint8_t>(decoded);
                        if (token >= 0x81 && token <= 0x9f) {
                            x += token & 0x1f; marker = 0; pending_high = false; continue;
                        }
                        if (is_class_marker(token)) {
                            marker = token; arrival = 0; first = true; pending_high = false; continue;
                        }
                        if (token >= 0xc0) {
                            high = token; pending_high = true; continue;
                        }
                        if (token < 0x80 && marker) {
                            uint32_t delta = token;
                            if (pending_high) delta |= uint32_t(high & 0x3f) << 7;
                            pending_high = false;
                            arrival = first ? delta : arrival + delta;
                            first = false;
                            if (x < width && (event_flag_mask & marker_bit(marker))) {
                                if (arrival_bins && (arrival >= arrival_bins_count || arrival_bins[arrival] < 0)) {
                                    ++local_overflow;
                                    continue;
                                }
                                const uint32_t bin = arrival_bins ? static_cast<uint32_t>(arrival_bins[arrival]) : std::min(
                                    bins - 1, uint32_t(uint64_t(arrival) * bins / period_bins));
                                if (bin >= bins) throw std::runtime_error("invalid calibrated bin mapping");
                                ++row_counts[size_t(bin) * width + x];
                                ++local_photons;
                                if (!arrival_bins && arrival >= period_bins) ++local_overflow;
                            }
                            continue;
                        }
                        marker = 0; pending_high = false;
                    }
                    if (reader.position() != job.end_bit) throw std::runtime_error("row did not consume exact bit length");
                    const uint32_t y = (row_model == 1
                        ? static_cast<uint32_t>((job.line % (uint64_t(height) * line_repetitions))
                                                / line_repetitions)
                        : job.line % height);
                    {
                        std::lock_guard<std::mutex> lock(row_mutexes[y]);
                        for (uint32_t bin = 0; bin < bins; ++bin) {
                            uint32_t* destination = output + (size_t(bin) * height + y) * width;
                            const uint32_t* source = row_counts.data() + size_t(bin) * width;
                            for (uint32_t column = 0; column < width; ++column) {
                                if (UINT32_MAX - destination[column] < source[column])
                                    throw std::runtime_error("uint32 histogram overflow");
                                destination[column] += source[column];
                            }
                        }
                    }
                    photons.fetch_add(local_photons, std::memory_order_relaxed);
                    overflows.fetch_add(local_overflow, std::memory_order_relaxed);
                    completed.fetch_add(1, std::memory_order_release);
                } catch (const std::exception& exc) {
                    failed.store(true);
                    std::lock_guard<std::mutex> lock(error_mutex);
                    if (worker_error.empty()) worker_error = "row " + std::to_string(job.line) + ": " + exc.what();
                }
            }
        };

        std::vector<std::thread> workers;
        workers.reserve(workers_count);
        for (uint32_t i = 0; i < workers_count; ++i) workers.emplace_back(worker);
        uint32_t reported = UINT32_MAX;
        while (completed.load(std::memory_order_acquire) < jobs.size() && !failed.load()) {
            const uint32_t current = completed.load(std::memory_order_acquire);
            if (progress && current != reported) { progress(current, uint32_t(jobs.size()), progress_data); reported = current; }
            if (cancel && *cancel) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(40));
            if (next_job.load() >= jobs.size() && completed.load() + workers_count >= jobs.size()) break;
        }
        for (auto& thread : workers) thread.join();
        if (progress) progress(completed.load(), uint32_t(jobs.size()), progress_data);
        if (failed.load()) throw std::runtime_error(worker_error.empty() ? "native worker failed" : worker_error);

        result->width = width; result->height = height; result->time_bins = bins;
        result->decoded_rows = completed.load(); result->photon_count = photons.load();
        result->overflow_count = overflows.load(); result->output_bits = 32;
        result->elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        if (cancel && *cancel) return 1;
        if (completed.load() != jobs.size()) throw std::runtime_error("native workers stopped before all rows completed");
        return 0;
    } catch (const std::exception& exc) {
        set_error(error, error_capacity, exc.what());
        return -1;
    } catch (...) {
        set_error(error, error_capacity, "unknown native decoder error");
        return -2;
    }
}

} // extern "C"

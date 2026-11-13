#include "leica_flim_decoder.h"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

// Additive API v3 extension. Python owns the bounded input batch and cube.
// Concurrent batches must not target the same cube. Within a batch, repeated
// acquisitions of a logical Y row are serialized; distinct Y rows are disjoint.
extern "C" LEICA_API int leica_decode_raw_batch(
    const uint8_t* data, uint64_t bytes, const uint64_t* offsets,
    const uint32_t* row_y, uint32_t rows, uint32_t width, uint32_t height,
    uint32_t bins, uint32_t period, uint32_t channel, uint32_t threads,
    void* output_cube, uint64_t output_bytes,
    uint64_t* photons_out, uint64_t* overflow_out, char* error, uint32_t capacity) {
    try {
        if (!data || !offsets || !row_y || !output_cube || !photons_out || !overflow_out)
            throw std::runtime_error("null raw batch pointer");
        if (!rows || !width || !height || !bins || !period || channel > 3)
            throw std::runtime_error("invalid raw batch dimensions or channel");
        const uint64_t pixels = uint64_t(width) * height;
        if (pixels > UINT64_MAX / bins / sizeof(uint32_t) ||
            output_bytes < pixels * bins * sizeof(uint32_t))
            throw std::runtime_error("raw output cube is too small");
        if (offsets[0] != 0 || offsets[rows] != bytes)
            throw std::runtime_error("raw batch offsets do not span input");
        for (uint32_t row = 0; row < rows; ++row)
            if (offsets[row + 1] <= offsets[row] || offsets[row + 1] > bytes ||
                (offsets[row + 1] - offsets[row]) % 2 || row_y[row] >= height)
                throw std::runtime_error("invalid raw row offset or Y coordinate");

        auto* output = static_cast<uint32_t*>(output_cube);
        std::vector<std::mutex> row_mutexes(height);
        std::atomic<uint32_t> next{0};
        std::atomic<uint64_t> photons{0}, overflow{0};
        std::atomic<bool> failed{false};
        std::mutex error_mutex;
        std::string worker_error;
        auto worker = [&]() {
            try {
                uint64_t local_photons = 0, local_overflow = 0;
                while (!failed.load(std::memory_order_relaxed)) {
                    const uint32_t row = next.fetch_add(1, std::memory_order_relaxed);
                    if (row >= rows) break;
                    const uint32_t y = row_y[row];
                    std::lock_guard<std::mutex> lock(row_mutexes[y]);
                    uint64_t boundaries = 0;
                    for (uint64_t pos = offsets[row]; pos < offsets[row + 1]; pos += 2) {
                        const uint32_t word = (uint32_t(data[pos]) << 8) | data[pos + 1];
                        const uint32_t high = word >> 12;
                        const uint32_t control_nibble = word & 0xF;
                        if ((high == 0xA || high == 0xB) &&
                            (control_nibble == 4 || control_nibble == 8)) {
                            ++boundaries;
                        } else if (high < 8 && (high >> 1) == channel) {
                            const uint64_t x = boundaries / 2;
                            if (x >= width) continue;
                            const uint32_t arrival = word & 0xFF;
                            const uint32_t bin = static_cast<uint32_t>(std::min<uint64_t>(
                                bins - 1, uint64_t(arrival) * bins / period));
                            uint32_t& cell = output[(uint64_t(bin) * height + y) * width + x];
                            if (cell == UINT32_MAX)
                                throw std::runtime_error("uint32 histogram overflow");
                            ++cell; ++local_photons;
                            if (arrival >= period) ++local_overflow;
                        }
                    }
                }
                photons.fetch_add(local_photons, std::memory_order_relaxed);
                overflow.fetch_add(local_overflow, std::memory_order_relaxed);
            } catch (const std::exception& exc) {
                failed.store(true);
                std::lock_guard<std::mutex> lock(error_mutex);
                if (worker_error.empty()) worker_error = exc.what();
            } catch (...) {
                failed.store(true);
                std::lock_guard<std::mutex> lock(error_mutex);
                if (worker_error.empty()) worker_error = "unknown raw worker error";
            }
        };
        const uint32_t count = std::max(1u, std::min({rows, 64u,
            threads ? threads : leica_recommended_threads()}));
        std::vector<std::thread> workers;
        workers.reserve(count);
        try {
            for (uint32_t i = 1; i < count; ++i) workers.emplace_back(worker);
            worker();
        } catch (...) {
            failed.store(true);
            for (auto& thread : workers) thread.join();
            throw;
        }
        for (auto& thread : workers) thread.join();
        if (failed.load()) throw std::runtime_error(worker_error);
        *photons_out = photons.load(); *overflow_out = overflow.load();
        return 0;
    } catch (const std::exception& exc) {
        if (error && capacity) {
            const size_t n = std::min<size_t>(capacity - 1, std::strlen(exc.what()));
            std::memcpy(error, exc.what(), n); error[n] = 0;
        }
        return -1;
    } catch (...) {
        if (error && capacity) error[0] = 0;
        return -2;
    }
}

#include "leica_flim_decoder.h"
#include <cstdlib>
#include <system_error>
#include <thread>
#include <vector>
#include <stdint.h>
#include <stddef.h>

#define LEICA_ALL_PHOTONS   0x100u
#define LEICA_FIRST_PHOTONS 0x200u
#define LEICA_SINGLE_EVENT  0x400u
#define LEICA_MAX_THREADS   64u

typedef struct RowBoundary {
    uint32_t has_photon;
    uint32_t first_x;
    uint32_t first_y;
    uint32_t first_arrival;
    uint32_t first_flag;
    uint32_t last_arrival;
} RowBoundary;

typedef struct DecodeTask {
    const uint8_t *data;
    uint64_t data_size;
    const uint64_t *offsets;
    const uint32_t *row_y;
    uint64_t row_count;
    uint32_t width;
    uint32_t height;
    uint32_t bins;
    uint32_t period;
    const int32_t *arrival_bins;
    uint32_t arrival_bins_count;
    uint32_t channel_index;
    uint32_t mode;
    uint32_t dead_time_bins;
    uint32_t worker_index;
    uint32_t worker_count;
    uint32_t *counts;
    uint64_t count_elements;
    uint64_t photons;
    uint64_t overflows;
    RowBoundary *boundaries;
    int status;
} DecodeTask;

static void copy_error(char *target, size_t target_size, const char *message) {
    size_t index = 0;
    if (target == NULL || target_size == 0) return;
    while (index + 1 < target_size && message[index] != '\0') {
        target[index] = message[index];
        ++index;
    }
    target[index] = '\0';
}

static int add_photon(DecodeTask *task, uint32_t x, uint32_t y, uint32_t arrival) {
    uint32_t output_bin;
    uint64_t index;
    uint32_t current;
    if (task->arrival_bins != NULL) {
        if (arrival >= task->arrival_bins_count || task->arrival_bins[arrival] < 0) {
            task->overflows += 1;
            return 0;
        }
        output_bin = (uint32_t)task->arrival_bins[arrival];
        if (output_bin >= task->bins) return 2;
    } else {
        if (arrival >= task->period) task->overflows += 1;
        output_bin = (uint32_t)(((uint64_t)arrival * task->bins) / task->period);
        if (output_bin >= task->bins) output_bin = task->bins - 1;
    }
    index = (((uint64_t)output_bin * task->height + y) * task->width) + x;
    if (index >= task->count_elements) return 2;
    current = task->counts[index];
    if (current == UINT32_MAX) return 3;
    task->counts[index] = current + 1u;
    task->photons += 1;
    return 0;
}

static int process_row(DecodeTask *task, uint64_t row) {
    uint64_t start = task->offsets[row];
    uint64_t end = task->offsets[row + 1];
    uint64_t position;
    uint32_t y = task->row_y[row];
    uint32_t control_count = 0;
    int have_cycle = 0;
    uint32_t cycle_count = 0;
    uint32_t candidate_x = 0;
    uint32_t candidate_arrival = 0;
    uint32_t previous_arrival = 0;
    int have_previous = 0;
    RowBoundary *boundary = task->boundaries == NULL ? NULL : &task->boundaries[row];

    if (start > end || end > task->data_size || ((end - start) & 1u) != 0 || y >= task->height) return 1;

    for (position = start; position < end; position += 2) {
        uint16_t word = (uint16_t)(((uint16_t)task->data[position] << 8) | task->data[position + 1]);
        uint32_t high = word >> 12;
        uint32_t control_nibble = word & 0x0fu;
        if ((high == 10u || high == 11u) && (control_nibble == 4u || control_nibble == 8u)) control_count += 1u;

        if (high < 8u && (high >> 1) == task->channel_index) {
            uint32_t x = control_count / 2u;
            uint32_t arrival;
            uint32_t first;
            int status;
            if (x >= task->width) continue;
            arrival = word & 0xffu;
            first = high & 1u;

            if (task->mode == LEICA_ALL_PHOTONS) {
                if (!have_previous) {
                    boundary->has_photon = 1u;
                    boundary->first_x = x;
                    boundary->first_y = y;
                    boundary->first_arrival = arrival;
                    boundary->first_flag = first;
                    have_previous = 1;
                } else if (first != 0u ||
                           (int32_t)arrival - (int32_t)previous_arrival >=
                               (int32_t)task->dead_time_bins) {
                    status = add_photon(task, x, y, arrival);
                    if (status != 0) return status;
                }
                previous_arrival = arrival;
                boundary->last_arrival = arrival;
                continue;
            }

            if (task->mode == LEICA_FIRST_PHOTONS) {
                if (first != 0u) {
                    status = add_photon(task, x, y, arrival);
                    if (status != 0) return status;
                }
                continue;
            }

            if (first != 0u) {
                if (have_cycle && cycle_count == 1u) {
                    status = add_photon(task, candidate_x, y, candidate_arrival);
                    if (status != 0) return status;
                }
                have_cycle = 1;
                cycle_count = 1u;
                candidate_x = x;
                candidate_arrival = arrival;
            } else if (have_cycle) {
                cycle_count += 1u;
            }
        }
    }
    /* The terminal cycle is excluded because the next boundary is unavailable. */
    return 0;
}

static unsigned int decode_worker(void* parameter) {
    DecodeTask *task = (DecodeTask *)parameter;
    uint64_t row;
    for (row = 0; row < task->row_count; ++row) {
        uint32_t y = task->row_y[row];
        if ((y % task->worker_count) != task->worker_index) continue;
        task->status = process_row(task, row);
        if (task->status != 0) break;
    }
    return 0;
}

/* ABI 2 adds an explicit calibrated arrival-to-bin mapping. */
extern "C" LEICA_API uint32_t leica_lmsraw_filter_api_version(void) { return 2u; }
extern "C" LEICA_API const char *leica_lmsraw_filter_version(void) { return "1.2.0"; }

extern "C" LEICA_API int leica_decode_raw_filtered_batch(
    const uint8_t *data, uint64_t data_size,
    const uint64_t *offsets, const uint32_t *row_y, uint64_t row_count,
    uint32_t width, uint32_t height, uint32_t bins, uint32_t period,
    const int32_t *arrival_bins, uint32_t arrival_bins_count,
    uint32_t channel_index, uint32_t mode, uint32_t thread_count,
    uint32_t *counts, uint64_t counts_bytes,
    uint64_t *photons, uint64_t *overflows,
    char *error, size_t error_size
) {
    DecodeTask tasks[LEICA_MAX_THREADS];
    std::vector<std::thread> handles;
    uint32_t workers;
    uint32_t index;
    uint64_t total_photons = 0;
    uint64_t total_overflows = 0;
    uint64_t expected_elements;

    if (error != NULL && error_size > 0) error[0] = '\0';
    if (data == NULL || offsets == NULL || row_y == NULL || counts == NULL || photons == NULL || overflows == NULL) {
        copy_error(error, error_size, "null input pointer"); return 1;
    }
    if (width == 0 || height == 0 || bins == 0 || period == 0 || row_count == 0) {
        copy_error(error, error_size, "invalid zero-sized decode parameter"); return 1;
    }
    if (mode != LEICA_FIRST_PHOTONS && mode != LEICA_SINGLE_EVENT) {
        copy_error(error, error_size, "unsupported LMSRAW filter mode"); return 1;
    }
    if (channel_index >= 4u) {
        copy_error(error, error_size, "invalid detector route"); return 1;
    }
    expected_elements = (uint64_t)width * height * bins;
    if (expected_elements > UINT64_MAX / sizeof(uint32_t) || counts_bytes < expected_elements * sizeof(uint32_t)) {
        copy_error(error, error_size, "histogram buffer is too small"); return 1;
    }
    if (offsets[0] != 0 || offsets[row_count] > data_size) {
        copy_error(error, error_size, "invalid LMSRAW batch offsets"); return 1;
    }

    workers = thread_count == 0u ? 1u : thread_count;
    if (workers > LEICA_MAX_THREADS) workers = LEICA_MAX_THREADS;
    if (workers > height) workers = height;
    if ((uint64_t)workers > row_count) workers = (uint32_t)row_count;

    for (index = 0; index < workers; ++index) {
        DecodeTask *task = &tasks[index];
        task->data = data; task->data_size = data_size; task->offsets = offsets;
        task->row_y = row_y; task->row_count = row_count; task->width = width;
        task->height = height; task->bins = bins; task->period = period;
        task->channel_index = channel_index; task->mode = mode; task->dead_time_bins = 0;
        task->worker_index = index; task->worker_count = workers; task->counts = counts;
        task->arrival_bins = arrival_bins; task->arrival_bins_count = arrival_bins_count;
        task->count_elements = expected_elements; task->photons = 0; task->overflows = 0;
        task->boundaries = NULL; task->status = 0;
    }

    for (index = 1; index < workers; ++index) {
        try {
            handles.emplace_back([&tasks, index]() { decode_worker(&tasks[index]); });
        } catch (const std::system_error&) {
            // Preserve the original synchronous fallback on thread exhaustion.
            decode_worker(&tasks[index]);
        }
    }
    decode_worker(&tasks[0]);
    for (auto& handle : handles) handle.join();

    for (index = 0; index < workers; ++index) {
        if (tasks[index].status != 0) {
            if (tasks[index].status == 1) copy_error(error, error_size, "invalid LMSRAW row boundaries");
            else if (tasks[index].status == 2) copy_error(error, error_size, "histogram index exceeded output buffer");
            else copy_error(error, error_size, "uint32 histogram overflow");
            return tasks[index].status;
        }
        total_photons += tasks[index].photons;
        total_overflows += tasks[index].overflows;
    }
    *photons = total_photons;
    *overflows = total_overflows;
    return 0;
}

extern "C" LEICA_API int leica_decode_raw_all_valid_batch(
    const uint8_t *data, uint64_t data_size,
    const uint64_t *offsets, const uint32_t *row_y, uint64_t row_count,
    uint32_t width, uint32_t height, uint32_t bins, uint32_t period,
    const int32_t *arrival_bins, uint32_t arrival_bins_count,
    uint32_t channel_index, uint32_t dead_time_bins,
    uint64_t global_first_row, uint64_t rows_per_plane,
    uint32_t initial_previous_valid, uint32_t initial_previous_arrival,
    uint32_t thread_count,
    uint32_t *counts, uint64_t counts_bytes,
    uint64_t *photons, uint64_t *overflows,
    uint32_t *final_previous_valid, uint32_t *final_previous_arrival,
    char *error, size_t error_size
) {
    DecodeTask tasks[LEICA_MAX_THREADS];
    std::vector<std::thread> handles;
    RowBoundary *boundaries = NULL;
    DecodeTask serial_task;
    uint32_t workers;
    uint32_t index;
    uint64_t row;
    uint64_t total_photons = 0;
    uint64_t total_overflows = 0;
    uint64_t expected_elements;
    uint32_t previous_valid = initial_previous_valid != 0u;
    uint32_t previous_arrival = initial_previous_arrival;

    if (error != NULL && error_size > 0) error[0] = '\0';
    if (data == NULL || offsets == NULL || row_y == NULL || counts == NULL ||
        photons == NULL || overflows == NULL || final_previous_valid == NULL ||
        final_previous_arrival == NULL) {
        copy_error(error, error_size, "null input pointer"); return 1;
    }
    if (width == 0 || height == 0 || bins == 0 || period == 0 || row_count == 0 ||
        dead_time_bins == 0u || rows_per_plane == 0u) {
        copy_error(error, error_size, "invalid zero-sized all-photons parameter"); return 1;
    }
    if (channel_index >= 4u) {
        copy_error(error, error_size, "invalid detector route"); return 1;
    }
    expected_elements = (uint64_t)width * height * bins;
    if (expected_elements > UINT64_MAX / sizeof(uint32_t) ||
        counts_bytes < expected_elements * sizeof(uint32_t)) {
        copy_error(error, error_size, "histogram buffer is too small"); return 1;
    }
    if (offsets[0] != 0 || offsets[row_count] > data_size) {
        copy_error(error, error_size, "invalid LMSRAW batch offsets"); return 1;
    }
    if (row_count > SIZE_MAX / sizeof(RowBoundary)) {
        copy_error(error, error_size, "LMSRAW batch is too large"); return 1;
    }
    boundaries = (RowBoundary *)std::calloc(static_cast<size_t>(row_count), sizeof(RowBoundary));
    if (boundaries == NULL) {
        copy_error(error, error_size, "unable to allocate LMSRAW row state"); return 1;
    }

    workers = thread_count == 0u ? 1u : thread_count;
    if (workers > LEICA_MAX_THREADS) workers = LEICA_MAX_THREADS;
    if (workers > height) workers = height;
    if ((uint64_t)workers > row_count) workers = (uint32_t)row_count;

    for (index = 0; index < workers; ++index) {
        DecodeTask *task = &tasks[index];
        task->data = data; task->data_size = data_size; task->offsets = offsets;
        task->row_y = row_y; task->row_count = row_count; task->width = width;
        task->height = height; task->bins = bins; task->period = period;
        task->channel_index = channel_index; task->mode = LEICA_ALL_PHOTONS;
        task->dead_time_bins = dead_time_bins; task->worker_index = index;
        task->worker_count = workers; task->counts = counts;
        task->arrival_bins = arrival_bins; task->arrival_bins_count = arrival_bins_count;
        task->count_elements = expected_elements; task->photons = 0; task->overflows = 0;
        task->boundaries = boundaries; task->status = 0;
    }

    for (index = 1; index < workers; ++index) {
        try {
            handles.emplace_back([&tasks, index]() { decode_worker(&tasks[index]); });
        } catch (const std::system_error&) {
            // Preserve the original synchronous fallback on thread exhaustion.
            decode_worker(&tasks[index]);
        }
    }
    decode_worker(&tasks[0]);
    for (auto& handle : handles) handle.join();

    for (index = 0; index < workers; ++index) {
        if (tasks[index].status != 0) {
            if (tasks[index].status == 1) copy_error(error, error_size, "invalid LMSRAW row boundaries");
            else if (tasks[index].status == 2) copy_error(error, error_size, "histogram index exceeded output buffer");
            else copy_error(error, error_size, "uint32 histogram overflow");
            std::free(boundaries);
            return tasks[index].status;
        }
        total_photons += tasks[index].photons;
        total_overflows += tasks[index].overflows;
    }

    serial_task = tasks[0];
    serial_task.photons = 0;
    serial_task.overflows = 0;
    for (row = 0; row < row_count; ++row) {
        RowBoundary *boundary = &boundaries[row];
        if (((global_first_row + row) % rows_per_plane) == 0u) previous_valid = 0u;
        if (boundary->has_photon == 0u) continue;
        if (boundary->first_flag != 0u ||
            (previous_valid != 0u &&
             (int32_t)boundary->first_arrival - (int32_t)previous_arrival >=
                 (int32_t)dead_time_bins)) {
            int status = add_photon(
                &serial_task, boundary->first_x, boundary->first_y,
                boundary->first_arrival);
            if (status != 0) {
                copy_error(error, error_size,
                           status == 2 ? "histogram index exceeded output buffer" :
                                         "uint32 histogram overflow");
                std::free(boundaries);
                return status;
            }
        }
        previous_valid = 1u;
        previous_arrival = boundary->last_arrival;
    }
    total_photons += serial_task.photons;
    total_overflows += serial_task.overflows;
    *photons = total_photons;
    *overflows = total_overflows;
    *final_previous_valid = previous_valid;
    *final_previous_arrival = previous_arrival;
    std::free(boundaries);
    return 0;
}

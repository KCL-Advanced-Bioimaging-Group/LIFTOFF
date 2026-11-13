#pragma once

#include <stdint.h>

#ifdef _WIN32
#define LEICA_API __declspec(dllexport)
#else
#define LEICA_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*leica_progress_callback)(uint32_t completed_rows,
                                        uint32_t total_rows,
                                        void* user_data);

typedef struct leica_decode_result {
    uint32_t width;
    uint32_t height;
    uint32_t time_bins;
    uint32_t decoded_rows;
    uint64_t photon_count;
    uint64_t overflow_count;
    uint32_t output_bits;
    double elapsed_seconds;
} leica_decode_result;

LEICA_API uint32_t leica_decoder_api_version(void);
LEICA_API const char* leica_decoder_version(void);
LEICA_API uint32_t leica_recommended_threads(void);

// Optional bounded LMSRAW extension (DLL >= 3.1). Adds counts to the existing
// cube. All input arrays remain caller-owned and must live through this call.
LEICA_API int leica_decode_raw_batch(
    const uint8_t* data, uint64_t bytes, const uint64_t* offsets,
    const uint32_t* row_y, uint32_t rows, uint32_t width, uint32_t height,
    uint32_t bins, uint32_t period, uint32_t channel, uint32_t threads,
    void* output_cube, uint64_t output_bytes,
    uint64_t* photons_out, uint64_t* overflow_out, char* error, uint32_t capacity);

// API v3 prepared context. The caller must keep compressed_block alive until
// leica_release_block is called.
LEICA_API int leica_prepare_block(
    const uint8_t* compressed_block,
    uint64_t compressed_size,
    void** decoder_context,
    uint32_t* encoded_rows,
    char* error_message,
    uint32_t error_message_capacity);

// API v6: arrival_bins optionally maps native indices to calibrated bins;
// negative or out-of-table entries are excluded and counted as overflow.
// API v5: event_flag_mask has four class bits per detector route (0..7).
// Route zero retains the API v4 mask; route r uses mask << (4*r).
LEICA_API int leica_decode_row_range(
    void* decoder_context,
    uint32_t first_row,
    uint32_t row_count,
    uint32_t width,
    uint32_t height,
    uint32_t time_bins,
    uint32_t native_period_bins,
    const int32_t* arrival_bins,
    uint32_t arrival_bins_count,
    uint32_t line_repetitions,
    uint32_t row_model,
    uint32_t event_flag_mask,
    uint32_t thread_count,
    void* output_cube,
    uint64_t output_cube_bytes,
    leica_progress_callback progress_callback,
    void* progress_user_data,
    const volatile uint32_t* cancellation_flag,
    leica_decode_result* result,
    char* error_message,
    uint32_t error_message_capacity);

LEICA_API void leica_release_block(void* decoder_context);

// Returns 0 on success, 1 on cancellation, and a negative value on error.
LEICA_API int leica_decode_histogram(
    const uint8_t* compressed_block,
    uint64_t compressed_size,
    uint32_t width,
    uint32_t height,
    uint32_t time_bins,
    uint32_t native_period_bins,
    const int32_t* arrival_bins,
    uint32_t arrival_bins_count,
    uint32_t line_repetitions,
    uint32_t row_model,
    uint32_t event_flag_mask,
    uint32_t thread_count,
    void* output_cube,
    uint64_t output_cube_bytes,
    leica_progress_callback progress_callback,
    void* progress_user_data,
    const volatile uint32_t* cancellation_flag,
    leica_decode_result* result,
    char* error_message,
    uint32_t error_message_capacity);

#ifdef __cplusplus
}
#endif

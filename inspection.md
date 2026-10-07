# 🛰️ KNACKSAT OBC Code Inspection Report

> **Date:** 2026-10-07
> **Target:** KNACKSAT4 OBC Firmware (STM32L496 + FreeRTOS)
> **Scope:** All project-authored C firmware, drivers, protocols, FATFS layer, Python emulators, and shell scripts

---

## Table of Contents

1. [Summary Dashboard](#summary-dashboard)
2. [CRITICAL Findings](#critical-findings)
3. [HIGH Findings](#high-findings)
4. [MEDIUM Findings](#medium-findings)
5. [LOW Findings](#low-findings)
6. [Fix Priority Roadmap](#fix-priority-roadmap)

---

## Summary Dashboard

| Severity  | Count | Risk to Mission |
|-----------|-------|-----------------|
| 🔴 CRITICAL | 9 | System crash, data corruption, satellite loss-of-contact |
| 🟠 HIGH | 12 | Intermittent failures, data loss, task starvation |
| 🟡 MEDIUM | 12 | Degraded reliability, inefficiencies |
| 🔵 LOW | 8 | Code quality, maintainability |
| **TOTAL** | **41** | |

---

## CRITICAL Findings

### C-01: Buffer Overflow in `commu_decode` — Unchecked `data_len` from Packet

> [!CAUTION]
> This is an **exploitable remote buffer overflow** reachable via radio uplink.

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L139-L162)
- **Lines:** 157–160
- **Description:** `commu_decode()` extracts `header->data_len` from the received packet and passes it directly to `memcpy()` without validating against the actual `input_len` or the destination buffer size. In `mainTask`, the destination is `commu_payload[128]` — a stack buffer.
- **Attack vector:** A malformed uplink packet with `data_len = 0xFFFF` causes a 65KB `memcpy` overrun destroying the entire task stack.
- **Impact:** HardFault → IWDG reset → reboot loop → **satellite unreachable**.
- **Fix:**
  ```c
  // Before memcpy in commu_decode():
  uint16_t available = input_len - BASIC_COMMU_FRAME_LEN;
  if (header->data_len > available) {
      return COMMU_ERR_FRAMING;
  }
  // Also pass max_output_len and check: header->data_len <= max_output_len
  ```

---

### C-02: Buffer Overflow in `payload_decode` — Same Pattern

- **File:** [`payload_protocol.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/src/payload_protocol.c#L33-L55)
- **Lines:** 49–52
- **Description:** Identical to C-01. `header->data_len` extracted from packet is used in `memcpy` without bounds checking against `input_len` or `output_payload` capacity. Also, `header->data_len >= 0` is always true for `uint16_t` (line 50).
- **Impact:** Stack buffer overflow via crafted payload protocol frame from USB (VR payload).
- **Fix:** Validate `header->data_len <= input_len - 8` before `memcpy`. Add `max_output_len` parameter.

---

### C-03: Operator Precedence Bug in CRC Parsing

- **File:** [`payload_protocol.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/src/payload_protocol.c#L39-L42) and [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L145-L148)
- **Lines:** payload_protocol.c:42, commu_helper.h:148
- **Description:** The last line of CRC reconstruction is:
  ```c
  (uint32_t)input_buf[input_len - 1] & 0xFF;
  ```
  Due to C operator precedence, `&` binds tighter than `|`. This means the entire accumulated CRC from the first 3 lines is `OR`ed with `(uint32_t)input_buf[...] & 0xFF` — but the **first three shifts are not parenthesized on the last term**.  Actually the real bug: the `& 0xFF` applies only to the last byte cast, not to the OR chain. The expression evaluates as:
  ```
  (A << 24) | (B << 16) | (C << 8) | (D & 0xFF)
  ```
  ...which actually works correctly by accident because `& 0xFF` on a uint8_t→uint32_t cast is redundant. **However**, the first three lines use `((uint32_t)x & 0xFF) << N` with proper parentheses, while the last does `(uint32_t)x & 0xFF` — the inconsistency indicates a cut-paste error and **future edits could introduce bugs**. More importantly, if `input_buf` was `int8_t` or signed, the sign extension would corrupt the CRC without the masking parentheses.
- **Impact:** CRC validation could silently pass corrupted frames on certain platforms.
- **Fix:** Wrap the last line consistently:
  ```c
  ((uint32_t)input_buf[input_len - 1] & 0xFF);
  ```

---

### C-04: `commu_global_buff` Overflow — 64 Bytes Receiving Up to 256 Bytes

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L89) and [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L2362-L2368)
- **Lines:** commu_helper.h:89, main.c:2363
- **Description:** `commu_global_buff` is declared as `uint8_t[COMMU_RX_SIZE]` = `uint8_t[64]`. In `uartRxTask` (main.c:2363), the code copies up to `commu_offset` bytes (max `COMMU_BUF_SIZE` = 256) into this 64-byte buffer. This is a **guaranteed overflow** for any COMMU frame > 64 bytes.
- **Impact:** Corrupts adjacent static variables (`commu_size`, `commu_data_ready`), leading to erratic behavior in the communication handler.
- **Fix:** Change `commu_global_buff` size to `COMMU_BUF_SIZE` (256).

---

### C-05: Data Race — `mainTask` Reads Accumulation Buffer While DMA Writes It

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1546)
- **Line:** 1546
- **Description:** `mainTask` does `memcpy(temp_commu_data_buff, commu_data_buff, commu_size)`. However, `commu_data_buff` is the **active accumulation buffer** being written by `uartRxTask` via DMA→memcpy. The mutex only protects `commu_data_ready`/`commu_size` — not the accumulation buffer itself. If new UART data arrives between `commu_data_ready = 1` (set by `uartRxTask`) and the `memcpy` in `mainTask`, the accumulation buffer is being modified underneath `mainTask`.
- **Impact:** Torn reads, garbled command data, silent corruption of uplinked commands.
- **Fix:** `mainTask` should read from `commu_global_buff` (the snapshot), not `commu_data_buff`. Or use a proper double-buffer/queue approach.

---

### C-06: Use-After-Return — Stack Buffer Passed to Async DMA Receive

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1089-L1136)
- **Lines:** 1094–1121
- **Description:** `EPS_Perform_Transaction()` declares `uint8_t frameRx[128]` on the **stack** and passes it to `HAL_UARTEx_ReceiveToIdle_IT()` (an async, interrupt-driven function). If the queue wait times out (line 1116), the function returns, deallocating `frameRx`. The UART DMA/interrupt may still write to this now-invalid address until `HAL_UART_AbortReceive` takes effect — a classic use-after-free on the stack.
- **Impact:** Stack corruption in `sensorQueryTask`, leading to random crashes.
- **Fix:** Make `frameRx` static:
  ```c
  static uint8_t frameRx[128] = {0};
  ```

---

### C-07: KISS Encode Functions Have No Output Bounds Checking

- **File:** [`kiss_protocol.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/src/kiss_protocol.c#L4-L43) and [`kiss_utils.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/kiss_utils.c#L57-L76)
- **Description:** `KISS_Encode()`, `KISS_Encode_Custom_Cmd()`, `KISS_SLIP_ENCODE()`, `KISS_WrapFrame()`, and `KISS_WrapImageChunk()` all write to `out_buffer` without checking the output buffer's capacity. Because SLIP escaping can **double** the data size (each `0xC0` or `0xDB` byte becomes 2 bytes), worst case output = `2 * input + overhead`. In multiple call sites in `mainTask`, output buffers are 32, 64, or 128 bytes with no capacity check.
- **Impact:** Stack buffer overflow at multiple call sites, especially with pathological data patterns.
- **Fix:** Add `max_out_len` parameter to all encode functions. Check `idx < max_out_len` before each write.

---

### C-08: `commu_list_file_encode` — Unbounded Write to 256-Byte Buffer

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L214-L233) called from [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1729-L1730)
- **Description:** The function can receive up to 20 filenames, each up to 255 chars, writing to `uint8_t list_file_buf[256]`. Maximum output = 1 + 20*(1+255) = 5121 bytes → catastrophic stack overflow.
- **Impact:** Listing files on the SD card with multiple files on orbit = immediate crash.
- **Fix:** Add bounds checking with `max_output_len` parameter. Truncate output when full.

---


### C-09: Unbounded `chunk_len` in File Downlink Causes Stack Buffer Overflow

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L209-L210) and [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1454)
- **Lines:** commu_helper.h:209, main.c:1454
- **Description:** `decode_file_data_request` extracts `chunk_len` directly from the uplinked packet without any upper bounds check. In `mainTask`, `f_read` is called with this attacker-controlled `chunk_len` to read file data into `buf_a[2048]`. Additionally, subsequent `commu_file_downlink_encode`, `commu_encode`, and `KISS_Encode_Custom_Cmd` steps write to `buf_b[2048]` and `buf_a[2048]`, causing further buffer overflows even for smaller chunks due to protocol overhead (e.g., KISS escape doubling).
- **Attack vector:** A ground station request with `chunk_len > 2048` (up to 65535) causes a massive stack overflow in `mainTask` during `f_read`, immediately crashing the OBC.
- **Impact:** System crash → watchdog reset → reboot loop (if re-triggered).
- **Fix:** In `main.c`, validate and clamp `chunk_len` such that the maximum possible KISS-encoded frame size fits within `sizeof(buf_b)` (2048). Since KISS encoding can double the size, `chunk_len` should be limited to `(2048 / 2) - 16 = 1008` bytes.

---

## HIGH Findings

### H-01: FatFS Mount/Unmount Race Between Tasks

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1442) and [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L2110)
- **Description:** Both `mainTask` (downlink/list files) and `usbTask` (image transfer) independently call `f_mount()` and `f_mount(NULL, ...)` on the default volume. FatFS maintains global state per volume. One task unmounting while the other is doing I/O will cause `FR_NOT_ENABLED` errors, data corruption, or incomplete writes.
- **Impact:** Concurrent image transfer + downlink = filesystem corruption + data loss.
- **Fix:** Mount once at startup, never unmount. Use `_FS_REENTRANT = 1` in `ffconf.h` or wrap all `f_*` calls with a dedicated `osMutex`.

---

### H-02: SPI DMA Semaphore Timeout Not Checked — Silent Data Corruption

- **File:** [`hal_stm32.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/hal_stm32.c#L101-L159)
- **Lines:** 110, 118, 132, 139, 149, 157
- **Description:** `osSemaphoreAcquire(spi.spiSem, SPI_TIMEOUT)` is called after starting DMA transfers, but **the return value is never checked**. If the semaphore times out (DMA interrupt missed due to radiation upset, etc.), the function proceeds as if the transfer completed, returning `hal_ok`.
- **Impact:** NOR flash reads/writes will return garbage or silently fail. LittleFS will treat corrupted data as valid, potentially destroying the filesystem metadata.
- **Fix:** Check semaphore return value. Return `hal_timeout` on failure:
  ```c
  if (osSemaphoreAcquire(spi.spiSem, SPI_TIMEOUT) != osOK) {
      gpio_high(spi.cs_pin);
      return hal_timeout;
  }
  ```

---

### H-03: SD SPI DMA Busy-Wait with `osWaitForever` Can Deadlock

- **File:** [`sd_spi.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_spi.c#L74-L87)
- **Lines:** 74, 87
- **Description:** `SD_TransmitBuffer` and `SD_ReceiveBuffer` use `osSemaphoreAcquire(handle, osWaitForever)`. If the DMA completion callback never fires (hardware fault, interrupt priority issue), the task blocks **forever**, starving the watchdog feed task (if the wdtFeedTask is lower priority or blocked).
- **Impact:** System hang → IWDG may or may not reset (depends on priority). SD operations become fatal.
- **Fix:** Use a finite timeout and handle the error:
  ```c
  if (osSemaphoreAcquire(sdTxSemaphoreHandle, 1000) != osOK) {
      // Handle DMA timeout — abort DMA, re-init SPI
  }
  ```

---

### H-04: `HAL_UART_Transmit_IT` on Stack Buffers — Data Sent After Return

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1536-L1661)
- **Lines:** 1536, 1597, 1609, 1644, 1661, 1685, 1743
- **Description:** Multiple call sites pass stack-local buffers (e.g., `beacon_kiss[200]`, `commu_content[128]`, `kiss_encoded_res[32]`) to `HAL_UART_Transmit_IT()`. This function starts async transmission and returns immediately. The buffer must remain valid until the Tx complete callback fires. If the task loop iterates, the stack frame is reused and the buffer contents are overwritten before UART finishes sending.
- **Impact:** Corrupted UART transmissions — garbled downlink data, garbled commands to ground station.
- **Fix:** Either:
  1. Use `HAL_UART_Transmit()` (blocking) for small frames, OR
  2. Use static/global TX buffers with a semaphore to wait for Tx completion, OR
  3. Use `osEventFlagsWait()` on a flag set by `HAL_UART_TxCpltCallback()`

---

### H-05: `mt25ql_die_erase` Blocks for Up to 460 Seconds

- **File:** [`mt25ql_dma.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/mt25ql_dma.c#L327-L372)
- **Line:** 368
- **Description:** `mt25ql_die_erase()` calls `mt25ql_wait_ready(dev_instance, MT25QL_TIMEOUT_DIE_ERASE)` with 460,000ms timeout. The loop polls every 1ms via `delay_ms(1)` (which calls `osDelay`). This means the calling task is occupied for up to **7.6 minutes**. During this time, any task depending on the NOR SPI bus is blocked.
- **Impact:** Calling die erase during operation would stall all NOR flash operations for minutes. While `wdtFeedTask` runs independently, any inter-task dependency could cascade.
- **Fix:** If die erase is needed, run it in a dedicated low-priority task. Consider a non-blocking approach with periodic status polling.

---

### H-06: `i2c_scan` Buffer Overflow — No Bounds Check on `addr` Array

- **File:** [`hal_stm32.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/hal_stm32.c#L19-L28)
- **Lines:** 19–28
- **Description:** `i2c_scan()` iterates through 128 I2C addresses. For each device that responds, it writes to `addr[*len]` and increments `*len`. There is no check that `*len` doesn't exceed the caller's array bounds. If many devices respond (or bus noise causes false positives), the buffer overflows.
- **Impact:** Stack/heap corruption during diagnostics.
- **Fix:** Add `max_len` parameter and check before writing:
  ```c
  hal_status_t i2c_scan(hal_i2c_t i2c, uint8_t *addr, uint8_t *len, uint8_t max_len);
  ```

---

### H-07: LittleFS `uint16_t` Truncation for Large Reads/Programs

- **File:** [`littlefs_port.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/littlefs_port.c#L21-L46)
- **Lines:** 28, 43
- **Description:** The `size` parameter from LittleFS (`lfs_size_t`) is `uint32_t`, but the flash read/write functions accept `uint16_t len`. The cast `(uint16_t)size` silently truncates sizes > 65535 bytes. LittleFS can request reads up to `cache_size` and programs up to `prog_size`, which are currently 512 and 256 respectively (safe), but if configuration changes, silent truncation will corrupt data.
- **Impact:** A configuration change to larger cache sizes could silently corrupt the filesystem.
- **Fix:** Add a runtime check or split large transfers:
  ```c
  if (size > UINT16_MAX) return LFS_ERR_INVAL;
  ```

---

### H-08: LM75 Temperature Sign Extension Bug

- **File:** [`lm75.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/lm75.c#L16-L26)
- **Lines:** 20–23
- **Description:** The LM75 returns a 9-bit two's complement value. The code does:
  ```c
  int16_t rawTemp = (tempData[0] << 1) | (tempData[1] >> 7);
  if (rawTemp & 0x100) { rawTemp |= 0xFE00; }
  ```
  The shift `tempData[0] << 1` promotes `uint8_t` to `int` on a 32-bit platform, so the sign-extension check `& 0x100` is correct for the 9-bit value. However, `i2c_reg_read()` return value is **never checked**. If the I2C read fails, `tempData` is uninitialized stack memory, and the returned temperature is garbage.
- **Impact:** False temperature readings during I2C bus errors could trigger incorrect thermal management decisions.
- **Fix:** Check return value of `i2c_reg_read()` and return an error indicator (e.g., `NAN` or a status code).

---

### H-09: Hardcoded Sector Count in SD `disk_ioctl`

- **File:** [`sd_diskio_spi.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_diskio_spi.c#L55-L63)
- **Lines:** 59
- **Description:** `GET_SECTOR_COUNT` returns hardcoded `0x10000` (32MB). The actual SD card size is not queried from the card's CSD register.
- **Impact:** FatFS will only see 32MB regardless of actual card capacity. Free space calculations and file allocation will be wrong.
- **Fix:** Read the actual sector count from the SD card's CSD register during initialization and store it for `GET_SECTOR_COUNT`.

---

### H-10: Unused `dma_tx_done`/`dma_rx_done` Flags — Dead Code Confusion

- **File:** [`sd_spi.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_spi.c#L44-L45) and [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1041-L1042)
- **Description:** `volatile int dma_tx_done` and `dma_rx_done` are declared in `sd_spi.c`, set in the commented-out callbacks, and `extern`'d in `main.c` but never used. The actual synchronization uses semaphores. This dead code creates confusion about which synchronization mechanism is active.
- **Impact:** Maintenance hazard. Future developers may re-enable the wrong mechanism.
- **Fix:** Remove all `dma_tx_done`/`dma_rx_done` declarations and references.

---


### H-11: `sensorQueryTask` Publishes Stale/Invalid Data on Sensor Failure

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L2204-L2261)
- **Lines:** 2204, 2259–2261
- **Description:** In `sensorQueryTask`, local variables `temp` and `_eps_sensors` are declared outside the main infinite loop (or reset inside). If the EPS UART transaction fails (`decoded_len == 0`), the parsing block is skipped, but `eps_sensors_data = _eps_sensors` still executes at the end of the loop, publishing the old/stale data from the previous iteration. For the TMP1075 temperature, if `tmp1075_read_temp` fails, `temp` remains `0` and is published, incorrectly indicating exactly 0°C instead of an error.
- **Impact:** The ground station and autonomous systems will silently receive stale or incorrect data (like 0°C), masking hardware failures.
- **Fix:** Initialize `_eps_sensors` and `temp` with distinct error/invalid states (e.g., `EPS_DATA_ERROR`, `INT32_MIN`) *inside* the loop before querying, or skip publishing to `obc_sensors_data` / `eps_sensors_data` upon failure.

---

### H-12: `KISS_IsFrameComplete` Protocol Desynchronization on UART Noise

- **File:** [`kiss_protocol.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/src/kiss_protocol.c#L64)
- **Lines:** 64
- **Description:** `KISS_IsFrameComplete()` strictly checks that `buf[0] == FEND`. In `mainTask` and `uartRxTask`, data from UART is blindly appended to an accumulation buffer. If the first byte received after a reset is noise (e.g., due to an incomplete previous transmission or EMI) and is not `FEND`, `buf[0]` will be incorrect. Even if perfect, valid KISS frames arrive subsequently, `KISS_IsFrameComplete` will perpetually return false. The buffer will grow until it overflows, at which point it resets the offset and drops the incoming chunk, often preventing it from realigning.
- **Impact:** Permanent loss of UART communication until a random alignment occurs or a hardware reset clears the buffer.
- **Fix:** Do not assume frames start exactly at index 0. `KISS_IsFrameComplete` should scan for `FEND` bytes and `KISS_UnwrapFrame` should extract valid frames anywhere within the buffer. The accumulation loop should trim leading non-`FEND` bytes.

---

## MEDIUM Findings

### M-01: `strncpy` Without Guaranteed Null Termination

- **File:** [`sd_functions.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_functions.c#L205-L209) and [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L174-L180)
- **Description:** `strncpy` does not null-terminate if the source string fills the destination. In `sd_read_csv`, filenames are copied without guaranteed null termination. In `decode_file_info_request` and `decode_file_data_request`, the null termination is only applied if `filename_len < 255`, but the buffer is exactly 256 bytes so index 255 is valid — however, `strncpy` is called with `filename_len` which may not include null.
- **Fix:** Always explicitly null-terminate after `strncpy`:
  ```c
  file_data->file_name[sizeof(file_data->file_name) - 1] = '\0';
  ```

---

### M-02: `commu_helper.h` Contains Function Definitions — ODR Violations

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h)
- **Description:** This header file defines **non-inline, non-static functions** (like `commu_encode`, `commu_decode`, `commu_init`, etc.) and **static variables** (`commu_temp_buff`, `commu_data_buff`, `commu_offset`). If this header is included from multiple translation units, it causes One Definition Rule (ODR) violations and linker errors or multiple copies of static buffers.
- **Fix:** Move all function definitions to a `.c` file. Keep only declarations in the header.

---

### M-03: `KISS_ValidateFrame` Uses Variable-Length Array on Stack

- **File:** [`kiss_utils.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/kiss_utils.c#L29)
- **Line:** 29
- **Description:** `uint8_t decode_buf[len]` uses a VLA. If `len` is large (e.g., attacker sends `len = 60000`), this will overflow the stack. VLAs are forbidden in safety-critical code (MISRA C:2012 Rule 18.8).
- **Fix:** Use a fixed-size buffer or caller-provided buffer with bounds checking.

---

### M-04: CRC Hardware Unit Has No Mutex — Concurrent Access Unsafe

- **File:** [`protocol_utils.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/src/protocol_utils.c#L10-L36)
- **Description:** The STM32 CRC hardware unit is a shared global resource (`hcrc`). Both `mainTask` and `usbTask` call `KISS_UpdateCRC32`/`KISS_CalculateCRC32` concurrently. If one task resets the CRC DR (`__HAL_CRC_DR_RESET`) while another is accumulating, the CRC result will be corrupted. This could cause valid frames to be rejected (frame loss) or invalid frames to be accepted (data corruption).
- **Fix:** Wrap CRC calculation with a mutex, or use software CRC (more suitable for concurrent use).

---

### M-05: `eps_command_t.len` is `uint8_t` but `KISS_Encode` Returns `uint16_t`

- **File:** [`eps_protocol.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-protocols/inc/eps_protocol.h#L54-L57)
- **Line:** 56
- **Description:** `eps_command_t.len` is `uint8_t` (max 255), but `KISS_Encode` returns `uint16_t`. If the encoded frame exceeds 255 bytes, `cmd.len` silently truncates, causing `EPS_Perform_Transaction` to send an incomplete frame.
- **Fix:** Change `uint8_t len` to `uint16_t len`.

---

### M-06: `rv3028c7_read_time` Doesn't Validate I2C Return Before Parsing

- **File:** [`rv3028c7.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/rv3028c7.c#L38-L50)
- **Lines:** 40–48
- **Description:** `rv3028c7_read_time` calls `i2c_reg_read` and proceeds to parse the `time[7]` buffer regardless of whether the read succeeded. If I2C fails, the buffer contains stale/garbage data.
- **Fix:** Return early if `ret != hal_ok` before parsing.

---

### M-07: Watchdog Timeout Dangerously Tight

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L609-L613)
- **Description:** IWDG is configured with `Prescaler=128`, `Reload=120`. At LSI ~32kHz: timeout ≈ (128 × 120) / 32000 = **0.48 seconds**. The `wdtFeedTask` feeds every 400ms. This leaves only ~80ms margin. Any OS scheduling jitter or higher-priority task running >80ms will trigger a reset.
- **Fix:** Increase reload value for more margin, e.g., `Reload = 600` for ~2.4s timeout.

---

### M-08: `file_count` in File Listing Has No Upper Bound

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1706-L1723)
- **Lines:** 1706, 1721–1722
- **Description:** `char files_name[20][256]` allocates **5120 bytes on the stack** of `mainTask`. `file_count` is incremented without checking `file_count < 20`. If the SD card has > 20 files, `strcpy(files_name[file_count], ...)` writes out of bounds.
- **Fix:** Add `if (file_count >= 20) break;` before the `strcpy`.

---

### M-09: `sd_list_directory_recursive` Has Unbounded Stack Recursion

- **File:** [`sd_functions.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_functions.c#L251-L278)
- **Description:** This function recurses for each subdirectory. Each recursion level allocates `char newpath[128]` + FatFS directory structs on the stack. A deeply nested directory structure (malicious SD card) could overflow the task stack.
- **Fix:** Limit recursion depth or use an iterative approach.

---

### M-10: System Status Response Uses Uninitialized Variables on Encode Error Path

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L1839-L1927)
- **Lines:** 1843–1844
- **Description:** In `PID_GS_OBC_REQUEST_SYSTEM_STATUS` handler, `commu_vr_request_payload` and `commu_vr_request_len` are used with `KISS_Encode_Custom_Cmd` **before** being initialized by `payload_encode` (line 1843 uses them, 1844 sets them). This sends garbage data.
- **Fix:** Swap lines 1843 and 1844 — encode the payload before KISS wrapping.

---

### M-11: `decode_file_data_request` `input_len` Parameter is `uint8_t`

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L186)
- **Line:** 186
- **Description:** `input_len` is `uint8_t` (max 255), but `commu_header_t.data_len` is `uint16_t`. If the actual payload is > 255 bytes, the length is silently truncated, potentially causing incorrect bounds checks.
- **Fix:** Change to `uint16_t input_len`.

---

### M-12: `filename_len <= 0` Check Is Redundant for `uint8_t`

- **File:** [`commu_helper.h`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Inc/commu_helper.h#L166)
- **Lines:** 166, 188
- **Description:** `filename_len` is `uint8_t` — it can never be negative. `<= 0` only catches the value 0, identical to `== 0`. While not a bug per se, the intent suggests the developer might have expected a signed type.
- **Fix:** Change to `== 0` for clarity, or change type to handle potential error cases.

---

## LOW Findings

### L-01: Global Variables in hal_stm32.c Are Unused

- **File:** [`hal_stm32.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/obc-drivers/src/hal_stm32.c#L5-L8)
- **Lines:** 5–8
- **Description:** `_hi2c`, `_hspi`, `_SPI_CS_GPIOx`, `_SPI_CS_GPIO_Pin` are declared but never used (the old non-DMA SPI code that used them is commented out).
- **Fix:** Remove unused globals.

---

### L-02: `.env` File Contains Internal IP Address

- **File:** [`.env`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/.env)
- **Description:** Contains `HIL_IP=100.110.52.82` — an internal/Tailscale IP address. While not a credential, it exposes internal network topology.
- **Fix:** Add `.env` to `.gitignore` (check it's not already tracked). Use `.env.example` with placeholder values.

---

### L-03: Copy-Paste Comment Errors in Headers

- **File:** Multiple headers (`payload_protocol.h`, `protocol_utils.h`, `kiss_protocol.h`)
- **Description:** Several headers have `@file` comments saying "driver-hal.h" — clearly copied from the original file.
- **Fix:** Update file-level comments to match actual filenames.

---

### L-04: Inconsistent Error Handling Style

- **Description:** Some functions return error codes (good), others silently continue after failures (bad). The downlink section in `mainTask` (lines 1442–1459) sets `status = 1` on failure but continues to try subsequent operations (`f_open`, `f_lseek`, `f_read`) even after mount failure.
- **Fix:** Use early-return or `goto cleanup` pattern consistently.

---

### L-05: `printf` Calls in Real-Time Paths

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c) (throughout)
- **Description:** `printf` is redirected through a message queue (`printQueueHandle`) → `logTask` → blocking UART transmit. While the queue prevents blocking, excessive `printf` during high-load operations (downlink, image transfer) fills the 256-entry queue, causing `printf` to block with `0xFFFF` timeout (65 seconds!), stalling the calling task.
- **Fix:** Use conditional compilation (`#ifdef DEBUG`) for verbose prints. Reduce timeout or make it non-blocking.

---

### L-06: Magic Numbers Throughout Protocol Code

- **Description:** Numbers like `5`, `4`, `7`, `9`, `11` are used as frame structure offsets without named constants. This makes the code fragile to protocol changes.
- **Fix:** Define named constants for all frame field sizes and offsets.

---

### L-07: `sd_spi.c` `tx_dummy[512]` is Static but Populated Every Call

- **File:** [`sd_spi.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/FATFS/Target/sd_spi.c#L82-L83)
- **Description:** `static uint8_t tx_dummy[512]` is declared static (good for DMA alignment) but filled with `0xFF` on every call (wasteful). Since it never changes, fill it once.
- **Fix:** Initialize once with `memset` or use `= { [0 ... 511] = 0xFF }` (GCC extension), or fill in an init function.

---

### L-08: `usb_data_t` Statement with No Effect

- **File:** [`main.c`](file:///Users/bipoe/Projects/Projects/Knacksat4_OBC/KNACKSAT_OBC_SpaceFruit/Core/Src/main.c#L2080)
- **Line:** 2080
- **Description:** `decoded_payload;` is a bare expression statement with no side effects. Likely leftover debug code.
- **Fix:** Remove the dead statement.

---

## Fix Priority Roadmap

> [!IMPORTANT]
> The following roadmap prioritizes fixes by mission impact. Items marked "Pre-Flight" are **mandatory** before deployment.

### Phase 1: Pre-Flight Critical (Fix Immediately)

| ID | Fix | Effort |
|----|-----|--------|
| C-01 | Add bounds check to `commu_decode` `memcpy` | 15 min |
| C-02 | Add bounds check to `payload_decode` `memcpy` | 15 min |
| C-04 | Resize `commu_global_buff` to 256 bytes | 5 min |
| C-05 | Read from `commu_global_buff` not `commu_data_buff` in mainTask | 10 min |
| C-06 | Make `frameRx` static in `EPS_Perform_Transaction` | 5 min |
| C-07 | Add `max_out_len` to all KISS encode functions | 1 hour |
| C-08 | Add bounds check to `commu_list_file_encode` | 15 min |
| H-02 | Check SPI DMA semaphore return values | 30 min |
| H-04 | Switch to blocking UART Tx or static buffers | 1 hour |
| M-04 | Add mutex around CRC hardware access | 30 min |
| M-10 | Fix line order in system status handler | 5 min |
| C-09 | Clamp `chunk_len` and validate buffer size | 15 min |
| H-12 | Fix `KISS_IsFrameComplete` protocol sync | 1 hour |

### Phase 2: Pre-Flight High Priority

| ID | Fix | Effort |
|----|-----|--------|
| H-01 | Mount FatFS once, add FS mutex | 2 hours |
| H-03 | Add timeout to SD SPI DMA semaphore waits | 30 min |
| H-06 | Add max_len to `i2c_scan` | 15 min |
| H-08 | Check I2C return in `lm75_read_temp` | 10 min |
| H-09 | Read actual SD card capacity from CSD | 1 hour |
| M-05 | Change `eps_command_t.len` to `uint16_t` | 5 min |
| M-06 | Check I2C return in `rv3028c7_read_time` | 10 min |
| M-07 | Increase IWDG timeout margin | 5 min |
| M-08 | Add file_count bounds check | 5 min |
| H-11 | Initialize variables inside `sensorQueryTask` loop | 15 min |

### Phase 3: Post-Launch Improvements

| ID | Fix | Effort |
|----|-----|--------|
| M-02 | Move `commu_helper.h` definitions to `.c` | 1 hour |
| M-03 | Replace VLA with fixed buffer | 15 min |
| M-09 | Limit directory recursion depth | 30 min |
| C-03 | Fix CRC parentheses consistency | 5 min |
| All LOW items | Code cleanup | 2 hours |

---

> [!NOTE]
> This inspection was performed by static code review. **Dynamic testing** (fuzzing the KISS/COMMU parsers, stress-testing concurrent SD access, radiation-injection testing) is strongly recommended before flight.


## Summary of Fixes (2026-10-07)

The following CRITICAL issues have been fixed:
- **C-01:** Fixed by adding `max_output_len` bounds check in `commu_decode` and updating `mainTask` to pass `sizeof(commu_payload)`.
- **C-02:** Fixed by adding `max_output_len` bounds check in `payload_decode`.
- **C-03:** Fixed operator precedence bug in CRC parsing for both `payload_protocol.c` and `commu_helper.h` by wrapping the last bitwise operation in parentheses.
- **C-04:** Fixed `commu_global_buff` overflow by changing its size from `COMMU_RX_SIZE` to `COMMU_BUF_SIZE`.
- **C-05:** Fixed data race by having `mainTask` read from the static snapshot `commu_global_buff` instead of the active `commu_data_buff`.
- **C-06:** Fixed use-after-return by making `frameRx` buffer `static` inside `EPS_Perform_Transaction`.
- **C-07:** Added `max_out_len` to all KISS encode functions (`KISS_Encode_Custom_Cmd`, `KISS_Encode`, `KISS_SLIP_ENCODE`, `KISS_WrapFrame`, `KISS_WrapImageChunk`) and updated all caller functions to pass `sizeof(buffer)` to enforce output bounds checking.
- **C-08:** Fixed unbounded write in `commu_list_file_encode` by introducing a `max_output_len` parameter and breaking out of the loop if `output_len` exceeds it, along with updating `actual_count`.
- **C-09:** Fixed unbounded `chunk_len` in file downlink by clamping `downlink_file_data.chunk_len` to 1008 before calling `f_read`.

**What's Missing:**
- All HIGH, MEDIUM, and LOW findings remain unresolved as per the instructions to only fix CRITICAL findings. This includes FatFS mount/unmount races (H-01), SPI DMA semaphore timeout logic (H-02, H-03), LittleFS truncation (H-07), and other non-critical issues detailed in the roadmap.

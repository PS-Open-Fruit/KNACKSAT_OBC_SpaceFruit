#ifndef __TASK_SHARED_H
#define __TASK_SHARED_H

#include "main.h"
#include "cmsis_os.h"
#include "fatfs.h"
#include "lfs.h"
#include "usbd_cdc_if.h"
#include "mt25ql.h"
#include "rv3028c7.h"
#include "tmp1075.h"
#include "littlefs_port.h"
#include "kiss_utils.h"
#include "obc_helper.h"
#include "eps_protocol.h"
#include "sd_spi.h"
#include "kiss_protocol.h"
#include "protocol_utils.h"
#include "commu_helper.h"
#include "time.h"
#include "payload_protocol.h"

// Defines from main.c
#define DOWNLINK_WINDOW_SIZE 5
#define NO_COMMU_TIMEOUT 10000
#define DATA_POLLING_INTERVAL 1000
#define BEACON_INTERVAL 10000
#define MAX_BEACON_PACKET_SIZE 256U

#define SYSTEM_STATE_BEACON         0x00000001U
#define SYSTEM_STATE_DOWNLINK       0x00000002U
#define SYSTEM_STATE_WAIT_ACK       0x00000004U
#define SYSTEM_STATE_ALL            0x00FFFFFFU

typedef enum{
      PAYLOAD_STATE_IDLE,
      PAYLOAD_STATE_RX,
} payload_state;

#define PAYLOAD_RX_TIMEOUT 3000

#define COM_UART huart4
#define EPS_UART huart2
#define DBG_UART huart3
#define SD_SPI hspi1
#define NOR_SPI hspi2

#define EVENT_FLAG_ERROR              0x80000000U
#define EPS_FLAG_POLL_START           0x00000001U
#define EPS_FLAG_POLL_SUCCESS         0x00000002U 
#define EPS_FLAG_POLL_ERROR           0x00000004U
#define EPS_FLAG_POLL_TIMEOUT         0x00000008U

#define PAYLOAD_FLAG_IDLE             0x00000020U
#define PAYLOAD_FLAG_POLL_CAPTURE     0x00000001U
#define PAYLOAD_FLAG_REQUEST_STATUS   0x00000002U
#define PAYLOAD_FLAG_RESPONSE_STATUS  0x00000100U
#define PAYLOAD_FLAG_IMAGE_REQUEST    0x00000004U
#define PAYLOAD_FLAG_IMAGE_TRANSFER   0x00000008U
#define PAYLOAD_FLAG_PING             0x00000040U
#define PAYLOAD_FLAG_RESPONSE_PING    0x00000080U
#define PAYLOAD_FLAG_IMAGE_DATA       0x00000010U

// Extern Variables
extern osEventFlagsId_t systemStateFlagHandle;
extern osEventFlagsId_t payloadFlagHandle;
extern osSemaphoreId_t norSemaphoreHandle;
extern osSemaphoreId_t epsSemaphoreHandle;
extern osSemaphoreId_t sdTxSemaphoreHandle;
extern osSemaphoreId_t sdRxSemaphoreHandle;
extern osMessageQueueId_t payloadStatueQueueHandle;

extern uint8_t eps_state;
// kiss_buffer and payload_kiss were declared but are they used in tasks? Let's just extern them.
extern uint8_t kiss_buffer[512];
// wait, kiss_frame_t needs kiss_protocol.h
#include "kiss_protocol.h"
extern kiss_frame_t payload_kiss;

extern lfs_t lfs;
extern lfs_file_t file;

// Helper functions
extern uint32_t unpack_be32(const uint8_t *buf);

extern IWDG_HandleTypeDef hiwdg;
extern UART_HandleTypeDef huart4;
extern UART_HandleTypeDef huart2;
extern UART_HandleTypeDef huart3;
extern UART_HandleTypeDef huart5;
extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi2;
extern I2C_HandleTypeDef hi2c4;
extern CAN_HandleTypeDef hcan2;

extern osMessageQueueId_t printQueueHandle;

extern eps_sensor_data_t eps_sensors_data;
extern obc_sensor_data_t obc_sensors_data;

extern osMutexId_t sensorsMutexHandle;
extern osThreadId_t sensorQueryHandle;
extern RTC_HandleTypeDef hrtc;
#include "usb_device.h"
extern uint16_t EPS_Perform_Transaction(uint8_t* cmd_buf, uint16_t cmd_len, uint8_t* out_buf);

extern uint8_t temp_buf[10000];
extern uint8_t payload_content[10000];
extern const uint32_t COMMU_RX_TIMEOUT;

#endif // __TASK_SHARED_H

#ifndef SUBSYSTEM_VR_H
#define SUBSYSTEM_VR_H

#include <stdint.h>
#include "main.h"

// VR Subsystem Constants - Ground-Driven Sliding Window Protocol
#define VR_CMD_PING         0x10
#define VR_CMD_STATUS_REQ   0x11
#define VR_CMD_CAPTURE      0x12
#define VR_CMD_FILE_INFO    0x14
#define VR_CMD_REQUEST      0x15
#define VR_CMD_REQUEST_ACK  0x16
#define VR_CMD_SYNC         0x17
#define VR_CMD_BURST        0x18
#define VR_CMD_REPORT       0x19
#define VR_CMD_FINAL        0x1A
#define VR_CMD_DATA         0x00  // Data frames

#define VR_STATUS_REQ       0x20  // Command from GS to request VR Status
#define VR_TIMEOUT_MS       5000  // VR Timeout in ms

typedef struct {
    uint8_t is_online;
    uint32_t last_seen_tick;
    uint8_t gs_ping_pending;
} VR_State_t;

void VR_Init(void);
void VR_Handle_Packet(uint8_t* payload, uint16_t len);
void VR_SendCmd(uint8_t cmd_id);
void VR_RequestGSPing(void);
void VR_Update(void);
uint8_t VR_IsOnline(void);

#endif

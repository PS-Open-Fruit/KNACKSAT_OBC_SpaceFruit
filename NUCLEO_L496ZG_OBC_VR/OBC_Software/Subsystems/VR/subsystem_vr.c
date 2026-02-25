#include "subsystem_vr.h"
#include "obc_packet.h"
#include "usbd_cdc_if.h" // For CDC_Transmit_FS
#include <string.h>
#include <stdio.h>

extern UART_HandleTypeDef hlpuart1; // Need access to send data to GS
extern uint32_t gs_led_timer; // GS LED Timer from main.c

VR_State_t vr_state;
uint32_t vr_led_timer = 0;

void VR_Init(void) {
    vr_state.last_seen_tick = 0;
    vr_state.is_online = 0;
    vr_state.gs_ping_pending = 0;
}

// Helper to Log via GS Link (duplicated from main.c for now, can be centralized later)
extern void OBC_Log(const char *fmt, ...); 

void VR_Handle_Packet(uint8_t* decoded, uint16_t dec_len) {
    // Mark VR as Online
    uint8_t was_online = vr_state.is_online;
    vr_state.is_online = 1;
    vr_state.last_seen_tick = HAL_GetTick();

    // Validate CRC
    if (dec_len < 5) {
        OBC_Log("[VR] Error: Payload short (%d)", dec_len);
        return;
    }
    
    // Extract CRC
    uint32_t rx_crc;
    memcpy(&rx_crc, &decoded[dec_len-4], 4);
    
    // Calc CRC
    uint32_t calc_crc = OBC_Calculate_CRC(decoded, dec_len-4);
    uint8_t kiss_cmd = decoded[0];
    uint8_t cmd_id = decoded[1];
    
    if (calc_crc != rx_crc) {
        OBC_Log("[VR] CRC Fail: %08X vs %08X (Cmd: %02X). Dropped.", rx_crc, calc_crc, cmd_id);
        return;
    }
    
    // Only process if it's a Data Frame
    if (kiss_cmd != 0x00) {
        return;
    }

    // Special handling for specific commands
    uint8_t forward_to_gs = 1;
    switch (cmd_id) {
        case VR_CMD_PING:
            if (!was_online) {
                OBC_Log("[VR] Connection Restored!");
            }
            HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_SET);
            vr_led_timer = HAL_GetTick();
            
            if (vr_state.gs_ping_pending) {
                OBC_Log("[VR] Pong!");
                vr_state.gs_ping_pending = 0;
                forward_to_gs = 1;
            } else {
                forward_to_gs = 0;
            }
            break;
            
        case VR_CMD_FILE_INFO:
            OBC_Log("[VR] File Info Received");
            HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_SET);
            vr_led_timer = HAL_GetTick();
            break;
            
        case VR_CMD_REQUEST_ACK:
            OBC_Log("[VR] Request ACK");
            HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_SET);
            vr_led_timer = HAL_GetTick();
            break;

        case VR_CMD_STATUS_REQ:
            // Status response from VR - forward as 0x21 to GS
            HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_SET);
            vr_led_timer = HAL_GetTick();
            break;

        default:
            break;
    }

    // Forward all packets to GS (including SYNC, BURST, DATA frames)
    if (forward_to_gs) {
        uint8_t gs_frame[1200];
        uint16_t gs_len = SLIP_Encode(decoded, dec_len, gs_frame);
        HAL_UART_Transmit(&hlpuart1, gs_frame, gs_len, 2000);
        
        // Blink GS LED
        HAL_GPIO_WritePin(LD1_GPIO_Port, LD1_Pin, GPIO_PIN_SET);
        gs_led_timer = HAL_GetTick();
    }
}

void VR_SendCmd(uint8_t cmd_id) {
    uint8_t payload[6];
    payload[0] = 0x00; // KISS Data
    payload[1] = cmd_id;
    
    uint32_t crc = OBC_Calculate_CRC(payload, 2); 
    memcpy(&payload[2], &crc, 4);
    
    uint8_t tx_frame[32];
    uint16_t len = SLIP_Encode(payload, 6, tx_frame);
    CDC_Transmit_FS(tx_frame, len);
}

void VR_RequestGSPing(void) {
    vr_state.gs_ping_pending = 1;
    VR_SendCmd(VR_CMD_PING);
}

void VR_Update(void) {
    uint32_t now = HAL_GetTick();

    // LED Off Logic
    if (vr_led_timer > 0 && (now - vr_led_timer > 50)) {
        HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_RESET);
        vr_led_timer = 0;
    }

    // Check Timeout
    if (vr_state.is_online && (now - vr_state.last_seen_tick > VR_TIMEOUT_MS)) {
        vr_state.is_online = 0;
        OBC_Log("[VR] Connection Lost (Timeout)");
    }

    // Auto-Ping (Keep-Alive)
    static uint32_t last_ping = 0;
    if (now - last_ping > 2000) {
        last_ping = now;
        VR_SendCmd(VR_CMD_PING);
    }
}

uint8_t VR_IsOnline(void) {
    return vr_state.is_online;
}

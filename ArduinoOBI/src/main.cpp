#include <Arduino.h>
#include "OneWire2.h"

/** Major version number (X.x.x) */
#ifndef ARDUINO_OBI_VERSION_MAJOR
#define ARDUINO_OBI_VERSION_MAJOR 0
#endif
/** Minor version number (x.X.x) */
#ifndef ARDUINO_OBI_VERSION_MINOR
#define ARDUINO_OBI_VERSION_MINOR 0
#endif
/** Patch version number (x.x.X) */
#ifndef ARDUINO_OBI_VERSION_PATCH
#define ARDUINO_OBI_VERSION_PATCH 0
#endif

#ifdef ESP_BUILD
#define ONEWIRE_PIN ESP_OW_PIN
#define ENABLE_PIN ESP_EN_PIN
#else
#define ONEWIRE_PIN 6
#define ENABLE_PIN 8
#endif


OneWire makita(ONEWIRE_PIN);

void cmd_and_read_33(byte *cmd, uint8_t cmd_len, byte *rsp, uint8_t rsp_len) {
	int i;
	makita.reset();
	delayMicroseconds(400);
	makita.write(0x33,0);

	for (i=0; i < 8; i++) {
		delayMicroseconds(90);
		rsp[i] = makita.read();
	}

	for (i=0; i < cmd_len; i++) {
		delayMicroseconds(90);
		makita.write(cmd[i],0);
	}

	for (i=8; i < rsp_len + 8; i++) {
		delayMicroseconds(90);
		rsp[i] = makita.read();
	}
}

void cmd_and_read_cc(byte *cmd, uint8_t cmd_len, byte *rsp, uint8_t rsp_len) {
	int i;
	makita.reset();
	delayMicroseconds(400);
	makita.write(0xcc,0);

	for (i=0; i < cmd_len; i++) {
		delayMicroseconds(90);
		makita.write(cmd[i],0);
	}

	for (i=0; i < rsp_len; i++) {
		delayMicroseconds(90);
		rsp[i] = makita.read();
	}
}

/* Debug/probe command for reverse-engineering batteries the web UI doesn't know yet.
 * Unlike the other commands, it exposes what they hide: the idle line level, the reset
 * presence pulse, and the timing between bytes (older BMSs may need different delays).
 *
 * data: [flags, post_reset_delay (x10 us), inter_byte_delay (us), bytes to write...]
 *   flags bit0: issue a 1-Wire reset before writing
 * rsp:  [idle_line_level, presence (0xFF = reset skipped), rsp_len - 2 bytes read...]
 *
 * Returns the number of payload bytes produced (0 when the request is malformed). */
#define DEBUG_FLAG_RESET 0x01

uint8_t cmd_debug_raw(byte *data, uint8_t data_len, byte *rsp, uint8_t rsp_len) {
	if (data_len < 3 || rsp_len < 2) {
		return 0;
	}
	uint8_t flags = data[0];
	uint16_t post_reset_delay_us = data[1] * 10;
	uint8_t inter_byte_delay_us = data[2];

	/* Idle level with ENABLE already high: a stuck-low line points to wiring or a BMS
	 * holding the bus, which reset() alone can't tell apart from "no device". */
	pinMode(ONEWIRE_PIN, INPUT);
	rsp[0] = digitalRead(ONEWIRE_PIN);

	rsp[1] = 0xFF;
	if (flags & DEBUG_FLAG_RESET) {
		rsp[1] = makita.reset();
		delayMicroseconds(post_reset_delay_us);
	}

	for (uint8_t i = 3; i < data_len; i++) {
		delayMicroseconds(inter_byte_delay_us);
		makita.write(data[i], 0);
	}

	for (uint8_t i = 2; i < rsp_len; i++) {
		delayMicroseconds(inter_byte_delay_us);
		rsp[i] = makita.read();
	}
	return rsp_len;
}

void cmd_and_read(byte *cmd, uint8_t cmd_len, byte *rsp, uint8_t rsp_len) {
	int i;
	makita.reset();
	delayMicroseconds(400);

	for (i=0; i < cmd_len; i++) {
		delayMicroseconds(90);
		makita.write(cmd[i],0);
	}

	for (i=0; i < rsp_len; i++) {
		delayMicroseconds(90);
		rsp[i] = makita.read();
	}
}


void setup() {
	Serial.begin (9600);
    // One-wire
	pinMode(ENABLE_PIN, OUTPUT);
	//pinMode(2, OUTPUT);
}

void send_usb(byte *rsp, byte rsp_len) {
    for (int i=0; i < rsp_len; i++) {
        Serial.write(rsp[i]);
    }
}

void read_usb() {
    if (Serial.available() >= 4) {
        byte start = Serial.read();
        byte cmd;
        byte len;
        byte data[255];
        byte rsp[255];
        byte rsp_len;

        if (start == 0x01) {
            len = Serial.read();
            rsp_len = Serial.read();
            cmd = Serial.read();
            if (len > 0){
                for (int i = 0; i < len; i++) {
                    while (Serial.available() < 1);
                    data[i] = Serial.read();
                }
            }
        }
        else {
            return;
        }
        /* Set RTS */
    	digitalWrite(ENABLE_PIN, HIGH);
	    delay(400);

        switch(cmd) {
            case 0x01:
                rsp[0] = 0x01;
                rsp[2] = ARDUINO_OBI_VERSION_MAJOR;
                rsp[3] = ARDUINO_OBI_VERSION_MINOR;
                rsp[4] = ARDUINO_OBI_VERSION_PATCH;
                break;
            case 0x31:
                makita.reset();
                delayMicroseconds(400);
                makita.write(0xcc,0);
                delayMicroseconds(90);
                makita.write(0x99,0);
                delay(400);
                makita.reset();
                delayMicroseconds(400);
                makita.write(0x31,0);
                delayMicroseconds(90);
                rsp[3] = makita.read();
                delayMicroseconds(90);
                rsp[2] = makita.read();
                delayMicroseconds(90);
                break;
            case 0x32:
                makita.reset();
                delayMicroseconds(400);
                makita.write(0xcc,0);
                delayMicroseconds(90);
                makita.write(0x99,0);
                delay(400);
                makita.reset();
                delayMicroseconds(400);
                makita.write(0x32,0);
                delayMicroseconds(90);
                rsp[3] = makita.read();
                delayMicroseconds(90);
                rsp[2] = makita.read();
                delayMicroseconds(90);
                break;
            case 0x33:
                cmd_and_read_33(data, len, &rsp[2], rsp_len);
                break;
            case 0xCC:
                cmd_and_read_cc(data, len, &rsp[2], rsp_len);
                break;
            case 0xD0:
                /* rsp has 255 bytes and 2 go to the header */
                if (rsp_len > 253) {
                    rsp_len = 253;
                }
                rsp_len = cmd_debug_raw(data, len, &rsp[2], rsp_len);
                break;
            default:
                rsp_len = 0;
                break;
        }
        rsp[0] = cmd;
        rsp[1] = rsp_len;
        send_usb(rsp, rsp_len + 2);

        digitalWrite(ENABLE_PIN, LOW);
    }
}

void loop() {
    read_usb();
}

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

/* Session command: several 1-Wire transactions while ENABLE stays high. Every other command
 * drops ENABLE when it answers, which takes the BMS out of test mode, so reads that only
 * answer in test mode (PackScope issue #13) must share one frame with the test-mode entry.
 *
 * data: transactions back to back, each [flags, delay_ms, write_len, read_len, write bytes...]
 *   flags bit0: 1-Wire reset before writing; delay_ms is waited before the transaction
 * rsp:  per transaction [presence (0xFF = reset skipped), read_len bytes...]
 *
 * The whole request is validated before anything goes on the bus, so a malformed frame
 * never runs half of its writes. Returns the payload length, or 0 when malformed. */
#define SESSION_HEADER_LEN 4

bool session_is_valid(byte *data, uint8_t data_len, uint8_t rsp_max) {
	uint16_t in = 0;
	uint16_t out = 0;
	while (in < data_len) {
		if (data_len - in < SESSION_HEADER_LEN) {
			return false;
		}
		uint8_t write_len = data[in + 2];
		uint8_t read_len = data[in + 3];
		in += SESSION_HEADER_LEN + write_len;
		out += 1 + read_len;
	}
	return in == data_len && out <= rsp_max;
}

uint8_t cmd_session(byte *data, uint8_t data_len, byte *rsp, uint8_t rsp_max) {
	if (data_len == 0 || !session_is_valid(data, data_len, rsp_max)) {
		return 0;
	}
	uint16_t in = 0;
	uint8_t out = 0;
	while (in < data_len) {
		uint8_t flags = data[in];
		uint8_t delay_ms = data[in + 1];
		uint8_t write_len = data[in + 2];
		uint8_t read_len = data[in + 3];
		in += SESSION_HEADER_LEN;

		delay(delay_ms);
		rsp[out] = 0xFF;
		if (flags & DEBUG_FLAG_RESET) {
			rsp[out] = makita.reset();
			delayMicroseconds(400);
		}
		out++;
		for (uint8_t i = 0; i < write_len; i++) {
			delayMicroseconds(90);
			makita.write(data[in++], 0);
		}
		for (uint8_t i = 0; i < read_len; i++) {
			delayMicroseconds(90);
			rsp[out++] = makita.read();
		}
	}
	return out;
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

/* A frame cut short (host closed the port mid-write) used to block read_usb() forever,
 * so every later command went unanswered until a reset. At 9600 baud a byte takes ~1 ms. */
#define SERIAL_BYTE_TIMEOUT_MS 50

bool read_serial_byte(byte *out) {
    unsigned long start = millis();
    while (Serial.available() < 1) {
        if (millis() - start > SERIAL_BYTE_TIMEOUT_MS) {
            return false;
        }
    }
    *out = Serial.read();
    return true;
}

/* rsp is 255 bytes and the first 2 are the header. 0x33 also stores the 8 ROM bytes in
 * front of the rsp_len bytes it reads, so it needs 8 more. */
#define RSP_PAYLOAD_MAX 253
#define RSP_PAYLOAD_MAX_33 (RSP_PAYLOAD_MAX - 8)

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
            for (int i = 0; i < len; i++) {
                if (!read_serial_byte(&data[i])) {
                    return;
                }
            }
        }
        else {
            return;
        }
        /* Every command sends rsp_len + 2 bytes of rsp, even the ones that fill fewer. */
        if (rsp_len > RSP_PAYLOAD_MAX) {
            rsp_len = RSP_PAYLOAD_MAX;
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
                if (rsp_len > RSP_PAYLOAD_MAX_33) {
                    rsp_len = RSP_PAYLOAD_MAX_33;
                }
                cmd_and_read_33(data, len, &rsp[2], rsp_len);
                break;
            case 0xCC:
                cmd_and_read_cc(data, len, &rsp[2], rsp_len);
                break;
            case 0xD0:
                rsp_len = cmd_debug_raw(data, len, &rsp[2], rsp_len);
                break;
            case 0xD1:
                rsp_len = cmd_session(data, len, &rsp[2], rsp_len);
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

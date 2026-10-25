#include <RadioLib.h>
#include <SPI.h>
#include <SSD1306Wire.h>

const int LORA_SCK = 9;
const int LORA_MISO = 11;
const int LORA_MOSI = 10;
const int LORA_NSS = 8;
const int LORA_DIO1 = 14;
const int LORA_RST = 12;
const int LORA_BUSY = 13;
const int OLED_SDA = 17;
const int OLED_SCL = 18;
const int OLED_RST = 21;
const int VEXT_CTRL = 36;
const uint8_t OLED_ADDR = 0x3C;

const float FREQ_MHZ = 915.0;
const float BW_KHZ = 125.0;
const uint8_t DEFAULT_SF = 7;
const uint8_t CODING_RATE = 5;
const int8_t TX_POWER_DBM = 14;
const uint16_t PREAMBLE_LEN = 8;
const float TCXO_VOLTAGE = 1.8;

const uint32_t SERIAL_BAUD = 115200;
const uint32_t FRAME_GAP_MS = 100;
const uint32_t TX_TIMEOUT_MS = 3000;

const uint8_t FRAME_START = 0xAA;
const uint8_t CMD_TRANSMIT = 'T';
const uint8_t CMD_PING = 'P';
const uint8_t CMD_SET_SF = 'S';
const uint8_t CMD_DISPLAY = 'O';
const uint8_t EVT_READY = 'B';
const uint8_t EVT_RECEIVED = 'R';
const uint8_t EVT_SENT = 'D';
const uint8_t EVT_RX_ERROR = 'E';

const size_t MAX_PACKET = 255;
const size_t MAX_FRAME_DATA = MAX_PACKET + 4;

SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY);
SSD1306Wire oled(OLED_ADDR, OLED_SDA, OLED_SCL);
bool oledOk = false;

volatile bool radioIrq = false;
bool transmitting = false;
uint32_t txStartedMs = 0;
int16_t radioStatus = RADIOLIB_ERR_NONE;
uint8_t currentSf = DEFAULT_SF;

enum ParseState { WAIT_START, READ_TYPE, READ_LEN_HI, READ_LEN_LO, READ_DATA, READ_CHECK };
ParseState parseState = WAIT_START;
uint8_t frameType = 0;
uint16_t frameLen = 0;
uint16_t framePos = 0;
uint8_t frameCheck = 0;
uint8_t frameData[MAX_FRAME_DATA];
bool frameReady = false;
uint32_t lastByteMs = 0;

uint8_t packetBuf[MAX_FRAME_DATA];

#if defined(ESP8266) || defined(ESP32)
ICACHE_RAM_ATTR
#endif
void onRadioIrq() {
  radioIrq = true;
}

void put16(uint8_t* buf, int16_t value) {
  buf[0] = (uint8_t)((uint16_t)value >> 8);
  buf[1] = (uint8_t)value;
}

void sendFrame(uint8_t type, const uint8_t* data, uint16_t len) {
  uint8_t header[4] = { FRAME_START, type, (uint8_t)(len >> 8), (uint8_t)len };
  uint8_t check = type ^ header[2] ^ header[3];
  for (uint16_t i = 0; i < len; i++) {
    check ^= data[i];
  }
  Serial.write(header, sizeof(header));
  if (len > 0) {
    Serial.write(data, len);
  }
  Serial.write(check);
}

void reportReady(int16_t status) {
  uint8_t data[3];
  put16(data, status);
  data[2] = currentSf;
  sendFrame(EVT_READY, data, sizeof(data));
}

void reportSent(int16_t status) {
  uint8_t data[2];
  put16(data, status);
  sendFrame(EVT_SENT, data, sizeof(data));
}

void reportRxError(int16_t status) {
  uint8_t data[2];
  put16(data, status);
  sendFrame(EVT_RX_ERROR, data, sizeof(data));
}

void startOled() {
  pinMode(VEXT_CTRL, OUTPUT);
  digitalWrite(VEXT_CTRL, LOW);
  delay(50);
  pinMode(OLED_RST, OUTPUT);
  digitalWrite(OLED_RST, LOW);
  delay(20);
  digitalWrite(OLED_RST, HIGH);
  delay(20);
  oledOk = oled.init();
  if (oledOk) {
    oled.flipScreenVertically();
  }
}

void drawText(uint8_t size, const uint8_t* text, uint16_t len) {
  if (!oledOk) {
    return;
  }
  const uint8_t* font = ArialMT_Plain_10;
  int lineHeight = 12;
  if (size == 1) {
    font = ArialMT_Plain_16;
    lineHeight = 18;
  } else if (size == 2) {
    font = ArialMT_Plain_24;
    lineHeight = 26;
  }

  int lines = 1;
  for (uint16_t i = 0; i < len; i++) {
    if (text[i] == '\n') {
      lines++;
    }
  }
  int y = size == 2 ? max(0, (64 - lines * lineHeight) / 2) : 0;
  int x = size == 2 ? 64 : 0;

  oled.clear();
  oled.setFont(font);
  oled.setTextAlignment(size == 2 ? TEXT_ALIGN_CENTER : TEXT_ALIGN_LEFT);
  String line;
  for (uint16_t i = 0; i <= len; i++) {
    if (i == len || text[i] == '\n') {
      oled.drawString(x, y, line);
      y += lineHeight;
      line = "";
    } else {
      line += (char)text[i];
    }
  }
  oled.display();
}

void showText(const char* text) {
  drawText(0, (const uint8_t*)text, strlen(text));
}

void handleDisplay() {
  if (frameLen >= 1) {
    drawText(frameData[0], frameData + 1, frameLen - 1);
  }
}

void listen() {
  radioIrq = false;
  radio.startReceive();
}

void finishTransmit(int16_t status) {
  radio.finishTransmit();
  transmitting = false;
  reportSent(status);
  listen();
}

void handleRadioIrq() {
  radioIrq = false;
  if (transmitting) {
    if (radio.getIrqFlags() & RADIOLIB_SX126X_IRQ_TX_DONE) {
      finishTransmit(RADIOLIB_ERR_NONE);
    }
    return;
  }

  size_t len = radio.getPacketLength();
  if (len > MAX_PACKET) {
    len = MAX_PACKET;
  }
  int16_t state = radio.readData(packetBuf + 4, len);
  if (state == RADIOLIB_ERR_NONE) {
    put16(packetBuf, (int16_t)lroundf(radio.getRSSI() * 10.0f));
    put16(packetBuf + 2, (int16_t)lroundf(radio.getSNR() * 10.0f));
    sendFrame(EVT_RECEIVED, packetBuf, len + 4);
  } else {
    reportRxError(state);
  }
  listen();
}

void startTransmit() {
  if (frameLen == 0 || frameLen > MAX_PACKET) {
    reportSent(RADIOLIB_ERR_PACKET_TOO_LONG);
    return;
  }
  radioIrq = false;
  int16_t state = radio.startTransmit(frameData, frameLen);
  if (state == RADIOLIB_ERR_NONE) {
    transmitting = true;
    txStartedMs = millis();
  } else {
    reportSent(state);
    listen();
  }
}

void setSpreadingFactor() {
  if (frameLen != 1) {
    reportReady(RADIOLIB_ERR_INVALID_SPREADING_FACTOR);
    return;
  }
  radio.standby();
  int16_t state = radio.setSpreadingFactor(frameData[0]);
  if (state == RADIOLIB_ERR_NONE) {
    currentSf = frameData[0];
  }
  listen();
  reportReady(state);
}

void handleFrame() {
  frameReady = false;
  if (frameType == CMD_TRANSMIT) {
    startTransmit();
  } else if (frameType == CMD_PING) {
    reportReady(radioStatus);
  } else if (frameType == CMD_SET_SF) {
    setSpreadingFactor();
  } else if (frameType == CMD_DISPLAY) {
    handleDisplay();
  }
}

void readSerial() {
  if (parseState != WAIT_START && millis() - lastByteMs > FRAME_GAP_MS) {
    parseState = WAIT_START;
  }
  while (!frameReady && Serial.available() > 0) {
    uint8_t b = (uint8_t)Serial.read();
    lastByteMs = millis();
    switch (parseState) {
      case WAIT_START:
        if (b == FRAME_START) {
          parseState = READ_TYPE;
        }
        break;
      case READ_TYPE:
        frameType = b;
        frameCheck = b;
        parseState = READ_LEN_HI;
        break;
      case READ_LEN_HI:
        frameLen = (uint16_t)b << 8;
        frameCheck ^= b;
        parseState = READ_LEN_LO;
        break;
      case READ_LEN_LO:
        frameLen |= b;
        frameCheck ^= b;
        framePos = 0;
        if (frameLen > MAX_FRAME_DATA) {
          parseState = WAIT_START;
        } else {
          parseState = frameLen > 0 ? READ_DATA : READ_CHECK;
        }
        break;
      case READ_DATA:
        frameData[framePos++] = b;
        frameCheck ^= b;
        if (framePos == frameLen) {
          parseState = READ_CHECK;
        }
        break;
      case READ_CHECK:
        frameReady = (b == frameCheck);
        parseState = WAIT_START;
        break;
    }
  }
}

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(SERIAL_BAUD);
  startOled();
  showText("LoRa PQC bridge\nstarting radio...");
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);

  radioStatus = radio.begin(FREQ_MHZ, BW_KHZ, DEFAULT_SF, CODING_RATE,
                            RADIOLIB_SX126X_SYNC_WORD_PRIVATE, TX_POWER_DBM,
                            PREAMBLE_LEN, TCXO_VOLTAGE);
  if (radioStatus == RADIOLIB_ERR_NONE) {
    radio.setDio1Action(onRadioIrq);
    listen();
    showText("LoRa PQC bridge\nradio ready, SF7\nwaiting for laptop");
  } else {
    String message = "LoRa PQC bridge\nRADIO FAILED\nstatus " + String(radioStatus);
    showText(message.c_str());
  }
  reportReady(radioStatus);
}

void loop() {
  if (radioIrq) {
    handleRadioIrq();
  }
  if (transmitting && millis() - txStartedMs > TX_TIMEOUT_MS) {
    finishTransmit(RADIOLIB_ERR_TX_TIMEOUT);
  }
  readSerial();
  if (frameReady && !transmitting && !radioIrq && radioStatus == RADIOLIB_ERR_NONE) {
    handleFrame();
  } else if (frameReady && radioStatus != RADIOLIB_ERR_NONE) {
    frameReady = false;
    reportReady(radioStatus);
  }
}

/*
 * =====================================================================
 *  Alcmaeon Lite  --  DAQ firmware
 * =====================================================================
 *
 *  Streams analog + digital channels to the Alcmaeon Lite desktop app
 *  as plain CSV, one line per sample:
 *
 *      <micros>,<a0>,<a1>,<a2>,<d0>,<d1>\n
 *
 *  Works with any EMG/ECG breakout that gives a plain analog output
 *  (MyoWare / MyoWare 2.0, Grove EMG, AD8232 ECG, Olimex EMG shield...).
 *
 *  WIRING (defaults below, Uno / Nano / Pro Mini)
 *  ---------------------------------------------
 *    A0  EMG board SIG      (board VCC -> 5V, GND -> GND, share GND!)
 *    A1  potentiometer 1 wiper   (ends to 5V and GND)
 *    A2  potentiometer 2 wiper
 *    D2  button 1 to GND    (uses the internal pull-up)
 *    D3  button 2 to GND
 *
 *  SERIAL COMMANDS (sent by the app, you can also type them in the
 *  Arduino Serial Monitor)
 *  ---------------------------------------------------------------
 *    S   start streaming
 *    X   stop streaming
 *    ?   print an info line, e.g.  #ALCMAEON,1,3,2,500
 *
 *  KEEP IN SYNC with alcmaeon/config.py:
 *    SAMPLE_RATE_HZ  <->  SAMPLE_RATE_HZ
 *    BAUD            <->  SERIAL_BAUD
 *    ANALOG_PINS     <->  ANALOG_CHANNELS   (same count, same order)
 *    DIGITAL_PINS    <->  DIGITAL_CHANNELS  (same count, same order)
 * =====================================================================
 */

// ---------------------------------------------------------------------
//  CONFIGURATION -- edit this block
// ---------------------------------------------------------------------

const uint8_t  ANALOG_PINS[]  = { A0, A1, A2 };
const uint8_t  DIGITAL_PINS[] = { 2, 3 };

const uint16_t SAMPLE_RATE_HZ = 500;      // samples per second, all channels
const uint32_t BAUD           = 250000;   // 115200 is only good to ~250 Hz here

const bool BUTTONS_USE_PULLUP = true;     // buttons wired to GND
const bool BUTTONS_ACTIVE_LOW = true;     // with pull-ups, pressed reads LOW
const bool FAST_ADC           = true;     // AVR only: ~5x faster conversions
const bool STREAM_ON_BOOT     = true;     // stream without waiting for 'S'

// ---------------------------------------------------------------------
//  Derived constants -- no need to edit below here
// ---------------------------------------------------------------------

const uint8_t  N_ANALOG    = sizeof(ANALOG_PINS);
const uint8_t  N_DIGITAL   = sizeof(DIGITAL_PINS);
const uint32_t SAMPLE_US   = 1000000UL / SAMPLE_RATE_HZ;

bool     streaming   = STREAM_ON_BOOT;
uint32_t nextSampleUs = 0;

// Reusable line buffer: micros (10) + channels (5 each) + commas + NUL.
char lineBuf[16 + 6 * (sizeof(ANALOG_PINS) + sizeof(DIGITAL_PINS))];

void setup() {
  Serial.begin(BAUD);

  for (uint8_t i = 0; i < N_DIGITAL; i++) {
    pinMode(DIGITAL_PINS[i], BUTTONS_USE_PULLUP ? INPUT_PULLUP : INPUT);
  }

#if defined(__AVR__)
  if (FAST_ADC) {
    // Default ADC prescaler of 128 gives ~9.6 kSPS, which is too slow to read
    // several channels at 500 Hz. Prescaler 16 -> ~77 kHz ADC clock, ~13.5 us
    // per conversion. Accuracy drops a little; still fine for EMG.
    ADCSRA = (ADCSRA & 0xF8) | 0x04;
  }
#endif

  printInfo();
  nextSampleUs = micros();
}

void loop() {
  handleCommands();
  if (!streaming) return;

  uint32_t now = micros();
  // Signed comparison handles the micros() rollover correctly.
  if ((int32_t)(now - nextSampleUs) < 0) return;
  nextSampleUs += SAMPLE_US;

  // If we ever fall behind (host stall, slow Serial), resync instead of
  // trying to catch up with a burst of samples.
  if ((int32_t)(micros() - nextSampleUs) > (int32_t)SAMPLE_US * 4) {
    nextSampleUs = micros() + SAMPLE_US;
  }

  sendSample(now);
}

// ---------------------------------------------------------------------

void sendSample(uint32_t stamp) {
  Serial.print(stamp);

  for (uint8_t i = 0; i < N_ANALOG; i++) {
    Serial.print(',');
    Serial.print(analogRead(ANALOG_PINS[i]));
  }

  for (uint8_t i = 0; i < N_DIGITAL; i++) {
    uint8_t raw = digitalRead(DIGITAL_PINS[i]);
    uint8_t pressed = BUTTONS_ACTIVE_LOW ? (raw == LOW) : (raw == HIGH);

    Serial.print(',');
    Serial.print(pressed);
  }

  Serial.println();
}

void handleCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    switch (c) {
      case 'S': case 's':
        streaming = true;
        nextSampleUs = micros();
        break;
      case 'X': case 'x':
        streaming = false;
        break;
      case '?':
        printInfo();
        break;
      default:
        break;   // ignore newlines and anything else
    }
  }
}

void printInfo() {
  // Lines beginning with '#' are informational; the app ignores them.
  Serial.print(F("#ALCMAEON,1,"));
  Serial.print(N_ANALOG);
  Serial.print(',');
  Serial.print(N_DIGITAL);
  Serial.print(',');
  Serial.println(SAMPLE_RATE_HZ);
}

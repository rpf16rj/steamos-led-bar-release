# Wiring diagram for ESP8266 + Wi-Fi option

## Power

```text
USB cable ──→ ESP8266 (powered via USB)
                 |
                 +── VV (5V pin) ──→ LED strip VCC
                 |                   (+ 74AHCT125 VCC if using Option A)
                 +── GND ──────────→ LED strip GND, 74AHCT125 GND
```

> For strips with more than 8 LEDs, use an external 5V supply for the strip (sharing GND with the ESP).

The ESP8266 GPIOs are **3.3 V only**. Do not connect the LED data line directly.

## LED data path

```text
ESP8266 GPIO 14 (D5 on NodeMCU/D1 mini) ----> 74AHCT125 1A (pin 2)
74AHCT125 /1OE (pin 1) ---------------------> GND   (active low)
74AHCT125 VCC (pin 14) ---------------------> 5 V
74AHCT125 GND (pin 7)  ---------------------> GND
74AHCT125 1Y (pin 3) ----> 330 Ω resistor --> WS2812B DIN
WS2812B VCC -------------------------------> 5 V
WS2812B GND -------------------------------> GND

[Optional] 1000 µF capacitor between WS2812B VCC and GND, close to the first LED
```

## 74AHCT125 pinout (one channel used)

```text
       +---U---+
 /1OE -| 1   14 |- VCC
  1A  -| 2   13 |- /4OE
  1Y  -| 3   12 |- 4A
 /2OE -| 4   11 |- 4Y
  2A  -| 5   10 |- /3OE
  2Y  -| 6    9 |- 3A
 GND  -| 7    8 |- 3Y
       +--------+
```

## Alternative: Diode instead of level shifter (simpler, recommended)

Instead of the 74AHCT125, a signal diode (e.g. 1N4148) works well. The WS2812B accepts 3.3V logic when VCC is 5V, especially with short wire runs.

```text
ESP8266 GPIO14 (D5) ───→ Diode (anode) ──→ (cathode) ──→ WS2812B DIN
```

No 330Ω resistor needed. The diode provides basic protection against back-feeding.

## Notes

- The default LED data pin in `main.cpp` is `GPIO14` (`D5` on NodeMCU / D1 mini). Change `#define LED_PIN` if you use another pin.
- The 74AHCT125 shifts the 3.3 V ESP8266 signal to 5 V logic required by the WS2812B input.
- The ESP8266 is powered via USB; the LED strip gets 5V from the ESP's VV pin.

# Module Lattice Key Encapsulation Mechanism over LoRa

 A post-quantum key exchange over the air between two Heltec WiFi LoRa 32 V3's, a long range wireless IoT development board. The handshake utilizes my implementation of Module
 Lattice Key Encapsulation Mechanism, which can be found at https://github.com/TheNotEvan/Post-Quantum-Crypto and X25519, a elliptic-curve Diffie-Hellman function.

 # Installation 

```
git clone https://github.com/TheNotEvan/MLKEM-over-LoRa
cd MLKEM-over-LoRa
pip install -r requirements.txt
```

# Running the program

For the program to work, you will need 2 Heltec Wifi LoRa 32 V3s. With an attena connected to each device:
* In Arduino IDE 2, install esp32 by Espressif Systems through the boards manager, and RadioLib through the library manager.
* Connect each LoRa device to a computer with a USB C cable, and upload bridge.ino to each device.

You can either use two computers, with a LoRa device connected to each, or two terminals on a single computer. On one computer/terminal, run the following command:
```
py -m scripts.demo bob {Device 1 Port}
```

On the second computer/terminal, run:

```
py -m scripts.demo alice {Device 2 Port}
```

When successful, Alice's terminal should look like this:

<img width="790" height="210" alt="image" src="https://github.com/user-attachments/assets/b1f564d6-15b1-4862-96af-f7d45c0ce649" />

# How it works

* Messages are split into 255-byte packets with a 6-byte header, which are then transmitted over radio.
* The receiving end notifies the sender which packets were lost during transmission, and those packets are resent until all of them are received.
* Both ends establish a shared secret key using ML-KEM and X25519, with a confirmation tag being used for implicit rejection.
* AES-GCM encryption and a nonce are used to encrypt session traffic

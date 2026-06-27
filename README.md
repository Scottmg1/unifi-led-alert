# unifi-led-alert

A lightweight Python daemon that controls the status LEDs on E7 UniFi Access Points to visually indicate power outages (via Network UPS Tools), local AP reachability, and global WAN health.

## LED Pattern Priorities
If multiple events occur simultaneously, the LED reflects the highest priority state (from top to bottom):

| Priority | Event State | Trigger | LED Behavior |
| :--- | :--- | :--- | :--- |
| **1** | `POWER_CRIT` | UPS Runtime <= 3m / Charge <= 20% | Fast Red Breathe |
| **2** | `POWER_LOW` | UPS Runtime <= 10m / Charge <= 50% | Slow Amber Pulse |
| **3** | `POWER_BATTERY` | UPS status is On Battery (Healthy) | Solid Amber (or Solid White) |
| **4** | `AP_DOWN` | Local Peer AP is unreachable | Purple Double-Blink |
| **5** | `WAN_DOWN` | WAN targets (DNS/Ping) fail | Rapid Red Flash |
| **6** | `NORMAL` | Normal operating conditions | LED Off |

## Prerequisites

1. An always-on Linux server (e.g., Ubuntu) that shares a UPS with the PoE switch feeding your APs.
2. Network UPS Tools (`nut`) configured on your server to monitor your UPS.
3. SSH access enabled on your UniFi Network Controller (Settings -> System -> Advanced -> Device Authentication).
4. `sshpass` installed on your server:
   ```bash
   sudo apt update && sudo apt install sshpass

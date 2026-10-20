# postmarketOS for LG Wine Smart (D486, `lg-vfp`)

This branch is upstream [pmaports](https://gitlab.postmarketos.org/postmarketOS/pmaports)
plus:

- `device/testing/device-lg-vfp`: device package (boots via lk2nd, extlinux on SD).
- `device/testing/linux-postmarketos-qcom-msm8226`: built from
  [egor835/linux `lg-vfp`](https://github.com/egor835/linux/tree/lg-vfp)
  (msm8226-mainline v6.16.12 + vfp drivers and DTS). Note this replaces the
  kernel for every msm8226 device built from this tree.

## What works

Display, backlight, touchscreen, keypad (PP2106), flip lid switch (suspend),
Wi-Fi/BT (wcn36xx, firmware from the modem partition), USB networking,
charging (500 mA, anti reverse boost), battery voltage and capacity, SD card,
GPU (freedreno, VRAM carveout, no IOMMU).

Not yet: modem, keypad backlight, real Wi-Fi MAC, GPU IOMMU.

## Install (SD card, eMMC untouched)

The phone needs [lk2nd](https://github.com/msm8916-mainline/lk2nd) (msm8226
build) flashed to the `boot` partition. With an SD card that has an extlinux
`/boot`, lk2nd boots postmarketOS; without it, it boots the Android image
stored after lk2nd.

```sh
git clone -b lg-vfp https://github.com/egor835/pmaports
pmbootstrap config aports "$PWD/pmaports"
pmbootstrap init          # vendor: lg, device: vfp, UI e.g. xfce4
pmbootstrap install --sdcard=/dev/sdX
```

Make sure the SD card has no leftover GPT: lk2nd and Android prefer it over
the MBR that pmbootstrap writes (`wipefs -a /dev/sdX` before installing).

UHS (SDR104) mode corrupted data on the tested cards, so the SD slot is
limited to 50 MHz high speed in the DTS.

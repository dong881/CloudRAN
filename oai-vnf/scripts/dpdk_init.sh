#!/bin/bash

sudo sh -c 'echo 0 > /sys/class/net/ens7f0/device/sriov_numvfs'
sudo sh -c 'echo 2 > /sys/class/net/ens7f0/device/sriov_numvfs'
sudo dpdk-devbind.py --unbind ca:01.0
sudo dpdk-devbind.py --unbind ca:01.1
sudo modprobe vfio_pci vfio-pci
sudo dpdk-devbind.py --bind vfio-pci ca:01.0
sudo dpdk-devbind.py --bind vfio-pci ca:01.1


# The MIT License (MIT)
# Copyright (c) 2019 Mike Teachman
# https://opensource.org/licenses/MIT
#
# MicroPython driver for the Texas Instruments TAS2505 Digital Input Class-D Speaker Amplifier
#

from micropython import const
import ustruct
import time
from collections import namedtuple

_register = namedtuple('Reg', 'num page')

_PAGE0 = const(0)
_PAGE1 = const(1)
_PAGE_SELECT = const(0x00)

class TAS2505():
    # special token used in a script to specify a time delay
    DELAY_MS = -999
    
    # page 0 configuration registers
    SOFTWARE_RESET = _register(1, _PAGE0)
    CLOCK_SETTING_1 = _register(4, _PAGE0)
    CLOCK_SETTING_2 = _register(5, _PAGE0)
    CLOCK_SETTING_3 = _register(6, _PAGE0)
    CLOCK_SETTING_4 = _register(7, _PAGE0)
    CLOCK_SETTING_5 = _register(8, _PAGE0)
    CLOCK_SETTING_6 = _register(11, _PAGE0)
    CLOCK_SETTING_7 = _register(12, _PAGE0)
    DAC_OSR_SETTING_1 = _register(13, _PAGE0)
    DAC_OSR_SETTING_2 = _register(14, _PAGE0)
    AUDIO_INTERFACE_SETTING_1 = _register(27, _PAGE0)
    DAC_INSTRUCTION_SET = _register(60, _PAGE0)
    DAC_CHANNEL_SETUP_1 = _register(63, _PAGE0)
    DAC_CHANNEL_SETUP_2 = _register(64, _PAGE0)
    DAC_CHANNEL_DIGITAL_VOLUME_CONTROL = _register(65, _PAGE0)
    
    # page 1 configuration registers
    REF_POR_LDO_BGAP_CONTROL = _register(1, _PAGE1)
    LDO_CONTROL = _register(2, _PAGE1)
    COMMON_MODE_CONTROL = _register(10, _PAGE1)
    SPEAKER_AMPLIFIER_CONTROL_1 = _register(45, _PAGE1)
    SPEAKER_VOLUME_CONTROL_1 = _register(46, _PAGE1)
    SPEAKER_AMPLIFIER_VOLUME_CONTROL_2 = _register(48, _PAGE1)
    
    # TODO:  define more registers to allow advanced users to configure
    # features such as digital filters 
    
    # Default script to configure playback mode, 16 bit I2S input, speaker output.
    # This script is a modification of the example 4.0.7 from 
    # page 49 in the TAS2505 Application Reference Guide
    # PLL used to create the DAC sampling freq 
    # Optimized for WAV files with 22.05kHz sampling, 16 bit samples
    # Values are specified in formats that best interpret the register bitfields
    # e.g. 0b00000101, 0x05, 5
    # Use this default script as a starting point to make customized configurations
    CONFIG_I2S_IN_SPEAKER_OUT = (
        (SOFTWARE_RESET,     0b00000001),
        # add recommended delay after reset of >1ms
        (DELAY_MS, 2),
        (LDO_CONTROL,     0b00000000), # 1.8V, level shifters powered up
        # Setup the clocks (see page 30 in the TAS2505 Application Reference Guide)
        # PLL provides the internal high speed clock (DAC_CLK) used by the DAC blocks
        # The I2S BCLK is the PLL input. 
        # Assume fs = 22.05kHz  (fs = audio sample rate)
        # BCLK freq = fs x 32 = 705.6 kHz (x32 because BCLK has 32 clock cycles for every sample) 
        # e.g.  I2S has L+R channels, each 16 bits, so 32 bits
        # PLL freq = BCLK freq x PLL muliplier
        # suppose we want PLL freq close to 30 MHz (note: must be <49.152 MHz)
        # results in PLL multiplier of 40
        # PLL freq = 705.6 kHz x 40 = 28.224 MHz
        # PLL multiplier = R x J.D / P
        # for PLL multiplier of 40:  R=1, J=40, D=0, P=1
        (CLOCK_SETTING_1, 0b00000111), # BCLK->PLL, PLL->CODEC_CLKIN
        (CLOCK_SETTING_2, 0b10010001), # Power up PLL, set P=1, R=1
        (CLOCK_SETTING_3, 40),# set J=40
        (CLOCK_SETTING_4, 0), # set D=0 (MSB)
        (CLOCK_SETTING_5, 0), # set D=0 (LSB)
        # add recommended delay of 15 ms for PLL to lock
        (DELAY_MS, 15),
        (CLOCK_SETTING_6, 0b10000001), # NDAC pwr'd up, NDAC = divide by 1 
        # MDAC and DOSR dividers will be used to reduce the DAC_CLK freq back to fs = 22.05kHz
        # need MDAC x DOSR = 1280. choose DOSR = 640, MDAC = 2 
        (CLOCK_SETTING_7, 0b10000010), # MDAC pwr'd up, MDAC = divide by 2
        (DAC_OSR_SETTING_1, 0x02), # DOSR = divide by 640 (0x280), MS = 0x02
        (DAC_OSR_SETTING_2, 0x80), # DOSR = divide by 640 (0x280), LS = 0x80
        (AUDIO_INTERFACE_SETTING_1, 0b00000000), # I2S, 16 bits
        (DAC_INSTRUCTION_SET, 0b00000010), # DAC Signal Processing Block PRB_P2
        (REF_POR_LDO_BGAP_CONTROL, 0b00010000), # Master Reference Powered on
        (COMMON_MODE_CONTROL, 0b00000000), # common mode is 0.9V
        (SPEAKER_VOLUME_CONTROL_1, 0), # 0dB gain
        (SPEAKER_AMPLIFIER_VOLUME_CONTROL_2, 0b00000000), # SPK muted by default
        (SPEAKER_AMPLIFIER_CONTROL_1, 0b00000010), # SPK powered up
        (DAC_CHANNEL_SETUP_1, 0b10010001), # DAC powered up, Soft step 2 per Fs, Left channel
        (DAC_CHANNEL_DIGITAL_VOLUME_CONTROL, 0), # 0dB gain
        (DAC_CHANNEL_SETUP_2, 0b00000100), # DAC volume not muted
        )
    
    def __init__(self, i2c):
        self._i2c = i2c
        self._address = 0x18 # fixed for this device
        
    def _set_page(self, page):
        wreg = ustruct.pack('B', page) 
        self._i2c.writeto_mem(self._address, _PAGE_SELECT, wreg)
        
    # writing a register consists of 2 steps:
    # 1. selecting the register page
    # 2. writing the register with a single byte value
    def _set_register(self, reg, value):
        self._set_page(reg.page)
        wreg = ustruct.pack('B', value)
        self._i2c.writeto_mem(self._address, reg.num, wreg)
        
    def read_register(self, reg):
        self._set_page(reg.page)
        ret = self._i2c.readfrom_mem(self._address, reg.num, 1)       
        return ret[0]
    
    # The following config() method configures device registers based on
    # an input script.
    # each line of the script has two elements:
    # 1. device register
    # 2. value to write to the register
    # A default script is provided.  
    # Most users will never need to change this script
    # nor will they want to figure out what all this stuff means.
    # Advanced users can create custom scripts to take 
    # full advantage of the device capabilities such as DAC filters.
    # TODO add error checking when processing a script
    def config(self, config_script=CONFIG_I2S_IN_SPEAKER_OUT):
        for action in config_script:
            if action[0] == TAS2505.DELAY_MS:
                time.sleep_ms(action[1])
            else:
                self._set_register(action[0], action[1])

    def set_speaker_amplifier_volume(self, volume):
        self._set_register(TAS2505.SPEAKER_AMPLIFIER_VOLUME_CONTROL_2, volume << 4)
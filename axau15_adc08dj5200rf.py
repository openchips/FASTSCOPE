#!/usr/bin/env python3

#
# This file is part of LiteX-Boards.
#
# Copyright (c) 2023 John Simons <jammsimons@gmail.com>
# SPDX-License-Identifier: BSD-2-Clause

import os

from migen import *

from litex.gen import *
from migen.genlib.resetsync import AsyncResetSynchronizer



from litex_boards.platforms import alinx_axau15
from litex.build.generic_platform import *
from litex.build.xilinx.common import DifferentialInput

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.led import LedChaser

from litedram.modules import MT40A512M16

from liteiclink.serdes.gth4_ultrascale import GTH4QuadPLL, GTH4

from litedram.phy import usddrphy

from litepcie.phy.usppciephy import USPPCIEPHY
from litepcie.software import generate_litepcie_software


from litejesd204b.common import *
from litejesd204b.core import LiteJESD204BCoreTX
from litejesd204b.core import LiteJESD204BCoreRX
from litejesd204b.core import LiteJESD204BCoreControl


# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst       = Signal()
        self.cd_sys    = ClockDomain()
        self.cd_sys4x  = ClockDomain()
        self.cd_idelay = ClockDomain()

        # # #

        # Clk.
        clk200 = platform.request("clk200")

        # PLL.
        self.pll = pll = USMMCM(speedgrade=-2)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys,    sys_clk_freq, with_reset=False)
        pll.create_clkout(self.cd_sys4x,  4*sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin) # Ignore sys_clk to pll.clkin path created by SoC's rst.
        self.idelayctrl = USIDELAYCTRL(cd_ref=self.cd_sys4x, cd_sys=self.cd_sys)

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(125e6),
        with_ethernet   = False,
        with_etherbone  = False,
        eth_ip          = "192.168.1.50",
        with_led_chaser = True,
        with_pcie       = False,
        **kwargs):
        platform = alinx_axau15.Platform()

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        kwargs["uart_name"] = "serial"
        SoCCore.__init__(self, platform, sys_clk_freq, ident="LiteX SoC on AXAU15", **kwargs)

        # DDR4 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.ddrphy = usddrphy.USPDDRPHY(platform.request("ddram"),
                memtype          = "DDR4",
                sys_clk_freq     = sys_clk_freq,
                iodelay_clk_freq = 500e6)
            self.add_sdram("sdram",
                phy           = self.ddrphy,
                module        = MT40A512M16(sys_clk_freq, "1:4"),
                size          = 0x40000000,
                l2_cache_size = kwargs.get("l2_size", 8192)
            )

        # PCIe -------------------------------------------------------------------------------------
        if with_pcie:
            self.pcie_phy = USPPCIEPHY(platform, platform.request("pcie_x4"),
                speed      = "gen3",
                data_width = 128,
                bar0_size  = 0x20000)
            self.add_pcie(phy=self.pcie_phy, ndmas=1)

        # Leds -------------------------------------------------------------------------------------
        if with_led_chaser:
            self.leds = LedChaser(
                pads         = platform.request_all("user_led"),
                sys_clk_freq = sys_clk_freq)
            


        #JESD204B
            

        adc08dj_phy               = "gth4"
        adc08dj_phy_rx_order      = [3, 0, 2, 1] #, 7, 4, 6, 5]
        adc08dj_phy_rx_lane_pol   = [0, 0, 0, 0, 1, 1, 1, 1]  # TODO: pass this to the PHY
        adc08dj_refclk_freq       = 156.25e6
        adc08dj_jesd_linerate     = 6.2500e9

        framing = True
        scrambling = True
        stpl_random = False

        # JESD Configuration -----------------------------------------------------------------------
        jesd_lanes = len(adc08dj_phy_rx_order)

        # 2 lanes / 4 converters / (4.9152Gbps linerate : IQ rate 61.44MSPS)
        if jesd_lanes == 2:
            raise NotImplementedError
        # 4 lanes / 4 converters / (2.4576Gbps linerate : IQ rate 122.88MSPS)
        elif jesd_lanes == 4:
            ps_tx = JESD204BPhysicalSettings(l=4, m=4, n=8, np=8)
            ts_tx = JESD204BTransportSettings(f=2, s=1, k=32, cs=0)
            settings_tx = JESD204BSettings(ps_tx, ts_tx, did=0x5a, bid=0x5, framing=framing, scrambling=scrambling)

            ps_rx = JESD204BPhysicalSettings(l=4, m=4, n=8, np=8)
            ts_rx = JESD204BTransportSettings(f=2, s=1, k=32, cs=0)
            settings_rx = JESD204BSettings(ps_rx, ts_rx, did=0x5a, bid=0x5, framing=framing, scrambling=scrambling)
         # 8 lanes / 8 converters / (6.25Gbps linerate)
        elif jesd_lanes == 8:
            #ps_tx = JESD204BPhysicalSettings(l=8, m=4, n=16, np=16)
            #ts_tx = JESD204BTransportSettings(f=2, s=1, k=32, cs=0)
            #settings_tx = JESD204BSettings(ps_tx, ts_tx, did=0x5a, bid=0x5, framing=framing, scrambling=scrambling)

            ps_rx = JESD204BPhysicalSettings(l=8, m=4, n=16, np=16)
            ts_rx = JESD204BTransportSettings(f=2, s=1, k=32, cs=0)
            settings_rx = JESD204BSettings(ps_rx, ts_rx, did=0x5a, bid=0x5, framing=framing, scrambling=scrambling)
        else:
            raise NotImplementedError

        platform.add_extension([
                ("adc08dj5200rf_refclk", 0,
                    # GTH clock (156.25 MHz)
                    Subsignal("p", Pins("HPC:GBTCLK0_M2C_P")),
                    Subsignal("n", Pins("HPC:GBTCLK0_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 0, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP0_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP0_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 1, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP1_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP1_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 2, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP2_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP2_M2C_N")),                    
                ),
                ("adc08dj5200rf_jesd_rx", 3, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP3_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP3_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 4, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP4_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP4_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 5, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP5_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP5_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 6, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP6_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP6_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_rx", 7, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP7_M2C_P")),
                    Subsignal("n",  Pins("HPC:DP7_M2C_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 0, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP0_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP0_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 1, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP1_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP1_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 2, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP2_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP2_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 3, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP3_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP3_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 4, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP4_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP4_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 5, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP5_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP5_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 6, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP6_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP6_C2M_N")),
                ),
                ("adc08dj5200rf_jesd_tx", 7, 
                    # # GTX data lanes
                    Subsignal("p",  Pins("HPC:DP7_C2M_P")),
                    Subsignal("n",  Pins("HPC:DP7_C2M_N")),
                ),

                # JSYNC
                ("adc08dj5200rf_sync", 0, Pins("HPC:LA28_P"), IOStandard("LVCMOS18")),

                # SYSREF 
                ("adc08dj5200rf_sysref", 0,
                    Subsignal("p", Pins("HPC:LA03_P"), IOStandard("LVDS")),
                    Subsignal("n", Pins("HPC:LA03_N"), IOStandard("LVDS"))
                ),
                
            #),
            #("adc08dj5200rf_spi", 0,
            #    # TODO: implement this
            #    Subsignal("cs_n", Pins("HPC:LA04_N FMC1_HPC:LA05_P")),
            #    Subsignal("miso", Pins("HPC:LA04_P"), Misc("PULLUP TRUE")),
            #    Subsignal("mosi", Pins("HPC:LA03_N")),
            #    Subsignal("clk",  Pins("HPC:LA03_P")),
            #    Subsignal("spi_en", Pins("HPC:LA05_N")),
            #    IOStandard("LVCMOS18")
            #),
        ])
            


        # JESD Clocking (Device) -------------------------------------------------------------------
        userclk_freq = adc08dj_jesd_linerate/40 # 6.25GHz / 40 = 156.25 MHz
        self.clock_domains.cd_jesd_156_25 = ClockDomain()
        self.clock_domains.cd_jesd_78_125 = ClockDomain()
        self.clock_domains.cd_jesd        = ClockDomain()
        self.clock_domains.cd_clk156_25   = ClockDomain()

        refclk_pads        = platform.request("adc08dj5200rf_refclk")
        refclk             = Signal()
        refclk_div2        = Signal()

        self.specials += Instance("IBUFDS_GTE4",
            i_CEB   = 0,
            i_I     = refclk_pads.p,
            i_IB    = refclk_pads.n,
            o_O     = refclk,
            o_ODIV2 = refclk_div2)


        self.submodules.pll = pll = USPMMCM(speedgrade=-2)
        pll.register_clkin(refclk_div2, adc08dj_refclk_freq/2)
        pll.create_clkout(self.cd_jesd_156_25, userclk_freq,   buf=None, with_reset=False)
        pll.create_clkout(self.cd_jesd_78_125,  userclk_freq/2, buf=None, with_reset=False)
        pll.create_clkout(self.cd_clk156_25,   156.25e6, with_reset=False)
        self.specials += Instance("BUFGMUX",
            #i_S  = self._speed.storage,
            i_I0 = ClockSignal("jesd_156_25"),
            i_I1 = ClockSignal("jesd_78_125"),
            o_O  = ClockSignal("jesd")
        )
        platform.add_period_constraint(refclk_div2, 1e9/(adc08dj_refclk_freq/2))

        # JESD Clocking (SYSREF) -------------------------------------------------------------------
        self.sysref = sysref = Signal()
        sysref_pads = platform.request("adc08dj5200rf_sysref")
        self.specials += DifferentialInput(sysref_pads.p, sysref_pads.n, sysref)

        # JESD PHYs --------------------------------------------------------------------------------
        jesd_pll_cls = {
            "gth4": GTH4QuadPLL,
            #"gtx": GTXQuadPLL,
            #"gtp": GTPQuadPLL,
        }[adc08dj_phy]
        jesd_phy_cls = {
            "gth4": GTH4
            #"gtx": GTX,
            #"gtp": GTP,
        }[adc08dj_phy]
        jesd_phy_data_width = {
             "gth4": 20, # 40?
            #"gtx": 20,
            #"gtp": 20,
        }[adc08dj_phy]

        jesd_pll = jesd_pll_cls(refclk, adc08dj_refclk_freq, adc08dj_jesd_linerate)
        self.submodules += jesd_pll
        #print(jesd_pll)

        self.jesd_phys = jesd_phys = []
        for i in range(jesd_lanes):
            jesd_tx_pads = platform.request("adc08dj5200rf_jesd_tx", i)
            jesd_rx_pads = platform.request("adc08dj5200rf_jesd_rx", i)
            jesd_phy = jesd_phy_cls(jesd_pll, jesd_tx_pads, jesd_rx_pads, sys_clk_freq,
                data_width       = jesd_phy_data_width,
                clock_aligner    = False,
                tx_buffer_enable = True,
                rx_buffer_enable = True)
            jesd_phy.add_stream_endpoints()
            jesd_phy.add_controls(auto_enable=False)
            jesd_phy.n = i
            setattr(self.submodules, "jesd_phy" + str(i), jesd_phy)
            platform.add_period_constraint(jesd_phy.cd_tx.clk, 1e9/jesd_phy.tx_clk_freq)
            platform.add_period_constraint(jesd_phy.cd_rx.clk, 1e9/jesd_phy.rx_clk_freq)
            platform.add_false_path_constraints(
                #soc.crg.cd_sys.clk,
                self.cd_jesd.clk,
                jesd_phy.cd_tx.clk,
                jesd_phy.cd_rx.clk)
            jesd_phys.append(jesd_phy)

        jesd_phys_tx_init_done = reduce(and_, [phy.tx_init.done for phy in jesd_phys])
        jesd_phys_rx_init_done = reduce(and_, [phy.rx_init.done for phy in jesd_phys])
        self.specials += AsyncResetSynchronizer(self.cd_jesd, ~(jesd_phys_tx_init_done & jesd_phys_rx_init_done))

        #jesd_phys_tx = [jesd_phys[n] for n in adc08dj_phy_tx_order]
        jesd_phys_rx = [jesd_phys[n] for n in adc08dj_phy_rx_order]

        # JESD TX ----------------------------------------------------------------------------------
        #self.submodules.jesd_tx_core    = LiteJESD204BCoreTX(jesd_phys_tx, settings_tx,
        #    converter_data_width = jesd_lanes*8,
        #    scrambling           = scrambling,
        #    stpl_random          = stpl_random)
        #self.submodules.jesd_tx_control = LiteJESD204BCoreControl(self.jesd_tx_core, sys_clk_freq)
        #self.jesd_tx_core.register_jsync(adc08dj5200rf_pads.request("adc08dj_sync_tx"))
        #self.jesd_tx_core.register_jref(sysref)

        # JESD RX ----------------------------------------------------------------------------------
        self.submodules.jesd_rx_core    = LiteJESD204BCoreRX(jesd_phys_rx, settings_rx,
            converter_data_width = jesd_lanes*8,
            scrambling           = scrambling,
            stpl_random          = stpl_random)
        self.submodules.jesd_rx_control = LiteJESD204BCoreControl(self.jesd_rx_core, sys_clk_freq)
        self.jesd_rx_core.register_jsync(platform.request("adc08dj5200rf_sync"))
        self.jesd_rx_core.register_jref(sysref)

        # JESD Link Status ------------------------------------------------------------------------------
        self.jesd_link_status = Signal()
        self.comb += self.jesd_link_status.eq(
            (self.jesd_rx_core.enable & self.jesd_rx_core.jsync) &
            (self.jesd_rx_core.enable & self.jesd_rx_core.jsync))
            

        

# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=alinx_axau15.Platform, description="LiteX SoC on AXAU15.")
    parser.add_target_argument("--sys-clk-freq",    default=125e6, type=float, help="System clock frequency.")
    parser.add_argument("--driver", action="store_true", help="Generate LitePCIe driver")

    #ethopts = parser.target_group.add_mutually_exclusive_group()
    #ethopts.add_argument("--with-ethernet",        action="store_true",    help="Enable Ethernet support.")
    #ethopts.add_argument("--with-etherbone",       action="store_true",    help="Enable Etherbone support.")
    #parser.add_target_argument("--eth-ip",         default="192.168.1.50", help="Ethernet/Etherbone IP address.")
    #parser.add_target_argument("--eth-dynamic-ip", action="store_true",    help="Enable dynamic Ethernet IP addresses setting.")
    args = parser.parse_args()

    #assert not (args.with_etherbone and args.eth_dynamic_ip)

    soc = BaseSoC(
        sys_clk_freq    = args.sys_clk_freq,
        #with_ethernet  = args.with_ethernet,
        #with_etherbone = args.with_etherbone,
        #eth_ip         = args.eth_ip,
        #eth_dynamic_ip = args.eth_dynamic_ip,
        **parser.soc_argdict
	)

    soc.add_sdcard()

    builder = Builder(soc, **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.driver:
        generate_litepcie_software(soc, os.path.join(builder.output_dir, "driver"))

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))

if __name__ == "__main__":
    main()

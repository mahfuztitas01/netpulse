# ============================================================================
# MikroTik RouterOS WireGuard (site-to-site to the NetPulse cloud VM)
# Requires RouterOS v7+.  Paste into the terminal (WebFig / WinBox -> New Terminal)
# after replacing the <...> placeholders.
#
# This makes the MikroTik the INITIATOR, so you do NOT need to expose SNMP or
# any management port to the internet. Only the cloud VM listens on UDP 51820.
# ============================================================================

# 1) Create the WireGuard interface
/interface/wireguard add name=wg-netpulse listen-port=51820 mtu=1420 comment="NetPulse tunnel"

# 2) Assign the tunnel IP (must match AllowedIPs on the cloud side)
/ip/address add address=10.200.0.2/24 interface=wg-netpulse comment="NetPulse tunnel IP"

# 3) [MANUAL ACTION] Copy the PRIVATE key printed here into the cloud peer config,
#    and put the CLOUD's public key in the `public-key` below.
:put ("MIKROTIK WG PUBLIC KEY: " . [/interface/wireguard get [find name=wg-netpulse] public-key])

# 4) Add the cloud VM as a peer (cloud public key + public IP)
/interface/wireguard/peers add \
    interface=wg-netpulse \
    public-key="<CLOUD_PUBLIC_KEY>" \
    endpoint-address=<CLOUD_PUBLIC_IP> \
    endpoint-port=51820 \
    allowed-address=10.200.0.0/24 \
    persistent-keepalive=25s \
    comment="NetPulse cloud"

# 5) Allow the tunnel traffic through the firewall
/ip/firewall/filter add chain=input in-interface=wg-netpulse action=accept comment="WG input"
/ip/firewall/filter add chain=forward in-interface=wg-netpulse action=accept comment="WG forward in"
/ip/firewall/filter add chain=forward out-interface=wg-netpulse action=accept comment="WG forward out"

# 6) NAT: let the cloud reach your LAN devices (they see the MikroTik LAN IP)
/ip/firewall/nat add chain=srcnat out-interface=bridge action=masquerade comment="NetPulse LAN access"
# NOTE: replace `bridge` with your actual LAN interface name (e.g. bridge, ether2)

# 7) (Optional) allow the cloud to resolve/route to additional subnets
# /ip/route add dst-address=10.200.0.0/24 gateway=wg-netpulse

# ---------------------------------------------------------------------------
# Verify from the cloud VM after the tunnel is up:
#     ping 10.200.0.2
#     ping <office-lan-ip>
#     snmpwalk -v2c -c <community> <office-lan-ip> 1.3.6.1.2.1.1.1.0
# ---------------------------------------------------------------------------

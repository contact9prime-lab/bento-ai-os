#!/bin/sh
# Build the stand-in Raspberry Pi for the Network tab's live run, from THIS machine's own
# installed packages (OpenSSH, sudo, nftables), because the run may have no package mirror.
# Needs a Debian or Ubuntu host with those packages and the bento-standby-base image
# (packaging/dev/standby-e2e). Usage: sh build.sh WORKDIR
set -e
W=${1:?usage: build.sh WORKDIR}
mkdir -p "$W"
for p in openssh-server openssh-client openssh-sftp-server sudo nftables libnftables1 libnftnl11 \
         libjansson4 libxtables12 libwrap0 libapparmor1 libedit2 libmnl0 libbsd0 libmd0; do
  dpkg -L "$p" 2>/dev/null
done | while read -r f; do { [ -f "$f" ] || [ -L "$f" ]; } && echo "$f"; done | sort -u > "$W/files.txt"
tar -chf "$W/pkgs.tar" -T "$W/files.txt" 2>/dev/null
cp "$(dirname "$0")/Dockerfile" "$W/Dockerfile"
docker build --network none -q -t bento-netbox "$W"

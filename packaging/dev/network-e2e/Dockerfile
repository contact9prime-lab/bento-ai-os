FROM bento-standby-base
ADD pkgs.tar /
# a stand-in Raspberry Pi: user pi with a password and passwordless sudo (Raspberry Pi OS's
# first user), SSH with password logins on and NO Include line (as Buster ships it)
RUN useradd -r -d /run/sshd -s /usr/sbin/nologin sshd && useradd -m -s /bin/bash pi && echo 'pi:raspberry-test-2' | chpasswd \
 && mkdir -p /etc/sudoers.d /run/sshd /etc/ssh/sshd_config.d && echo 'pi ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/010_pi-nopasswd \
 && chmod 440 /etc/sudoers.d/010_pi-nopasswd && rm -f /etc/ssh/sshd_config.d/* \
 && printf 'Port 22\nPasswordAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM yes\nSubsystem sftp /usr/lib/openssh/sftp-server\n' > /etc/ssh/sshd_config \
 && ssh-keygen -A && touch /etc/nftables.conf
ENTRYPOINT []
CMD ["/usr/sbin/sshd", "-D", "-e"]

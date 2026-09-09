# Stage 1: Base image with apt packages
FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbullseye-8446af38-ls104 AS base

ENV TITLE=MetaTrader
ENV WINEARCH=win64
ENV WINEPREFIX="/config/.wine"
ENV DISPLAY=:0

# Ensure the directory exists with correct permissions
RUN mkdir -p /config/.wine && \
    chown -R abc:abc /config/.wine && \
    chmod -R 755 /config/.wine

# Comment out the backports entry and remove stale nodesource repo
RUN sed -i '/bullseye-backports/s/^/#/' /etc/apt/sources.list /etc/apt/sources.list.d/*.list || true && \
    rm -f /etc/apt/sources.list.d/nodesource.list

# Bullseye is EOL: security.debian.org's Release file expires faster than this
# image gets rebuilt, which makes apt-get update fail outright. Skip the
# valid-until check so stale-but-still-served metadata doesn't hard-fail the build.
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until

# Bullseye's security repo is mid-decommission: its Packages index still lists
# point-releases whose .deb files have already been pruned from the mirror, so a
# full `apt-get upgrade` 404s on packages we don't even use. --fix-missing can't
# help here (it only covers locally missing/corrupt files, not remote 404s), and
# a full base-image upgrade isn't needed for the handful of packages installed
# below, so just refresh the index and skip upgrading the rest of the image.
RUN apt-get update

# Install required packages
RUN apt-get install -y \
    dos2unix \
    python3-pip \
    wget \
    python3-pyxdg \
    netcat \
    && pip3 install --upgrade pip

# Add WineHQ repository key and APT source
RUN wget -q https://dl.winehq.org/wine-builds/winehq.key > /dev/null 2>&1\
    && apt-key add winehq.key \
    && add-apt-repository 'deb https://dl.winehq.org/wine-builds/debian/ bullseye main' \
    && rm winehq.key

# Add i386 architecture and update package lists
RUN dpkg --add-architecture i386 \
    && apt-get update

# Install WineHQ stable package and dependencies
RUN apt-get install --install-recommends -y \
    winehq-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Final image
FROM base

# Copy the scripts directory and convert start.sh to Unix format
COPY app /app
COPY scripts /scripts
RUN dos2unix /scripts/*.sh && \
    chmod +x /scripts/*.sh

COPY /root /
RUN touch /var/log/mt5_setup.log && \
    chown abc:abc /var/log/mt5_setup.log && \
    chmod 644 /var/log/mt5_setup.log

EXPOSE 3000 5000 5001 8001 18812
VOLUME /config

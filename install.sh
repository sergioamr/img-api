#!/usr/bin/env bash

cd "${BASH_SOURCE%/*}"

sudo apt update
sudo apt install software-properties-common  -y

echo "VIRTUAL ENV INSTALL"

sudo apt-get install python3-pip python3-venv -y   # If needed
#sudo pip3 install virtualenv

echo "VIRTUAL ENV INSTALL"
sudo python3 -m pip install virtualenv

echo "VIRTUAL ENV2"
python3 -m virtualenv .venv --python=python3
source .venv/bin/activate

echo "MONGODB INSTALL"
curl -fsSL https://www.mongodb.org/static/pgp/server-4.4.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/4.4 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-4.4.list
sudo apt update

sudo apt-get install mongodb-org -y

echo "START MONGO"
sudo systemctl start mongod
sudo systemctl status mongod
sudo systemctl enable mongod

echo "IMAGE MAGICK"
sudo apt install imagemagick -y

echo "IMAGE MAGICK"
sudo apt install redis -y

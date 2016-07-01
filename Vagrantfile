# -*- mode: ruby -*-
# vi: set ft=ruby :

# Install docker
$docker_setup = <<SCRIPT
set -e

# Install Docker
curl -sSL https://get.docker.com/ | sh
sudo usermod -aG docker vagrant

# Set up the docker registry
sudo mkdir -p /registry
sudo docker create -p 5000:5000 -v /registry:/tmp/registry-dev --name=registry registry:0.9.1
(sudo docker start registry || true)

# Setup Mesos
sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv E56151BF
DISTRO=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
CODENAME=$(lsb_release -cs)

echo "deb http://repos.mesosphere.com/${DISTRO} ${CODENAME} main" | \
  sudo tee /etc/apt/sources.list.d/mesosphere.list
sudo apt-get -y update
sudo apt-get -y install mesos

sudo bash -c "echo 192.168.33.50 > /etc/mesos-master/ip"
sudo bash -c "echo 192.168.33.50 > /etc/mesos-slave/ip"
sudo bash -c "echo 192.168.33.50 > /etc/mesos-slave/hostname"
sudo bash -c "echo docker,mesos > /etc/mesos-slave/containerizers"

# Start a bunch of services
sudo service zookeeper restart
sleep 5
(sudo service mesos-master stop || true)
(sudo service mesos-slave stop || true)

# Start mesos
sudo service mesos-master start
sudo service mesos-slave start

# Install portainer dependencies
sudo apt-get install -y python-setuptools
sudo easy_install pip
sudo pip install virtualenv
SCRIPT

Vagrant.configure("2") do |config|

  # Use the same base box as vagrant-web
  config.vm.box = "ubuntu/trusty64"

  config.vm.synced_folder "./", "/opt/portainer"
  config.vm.network :private_network, ip: "192.168.33.50"

  # Configure the VM with 1024Mb of RAM and 2 CPUs
  config.vm.provider :virtualbox do |vb|
    vb.customize ["modifyvm", :id, "--memory", "1024"]
    vb.customize ["modifyvm", :id, "--cpus", "2"]
  end

  # Install all the things!
  # config.vm.provision "shell", inline: $docker_setup
end

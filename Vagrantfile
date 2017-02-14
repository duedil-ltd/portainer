# -*- mode: ruby -*-
# vi: set ft=ruby :

# Install docker
$docker_setup = <<SCRIPT
set -e

# Setup
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv E56151BF
DISTRO=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
CODENAME=$(lsb_release -cs)

# Add the repository
echo "deb http://repos.mesosphere.io/${DISTRO} ${CODENAME} main" | \
  sudo tee /etc/apt/sources.list.d/mesosphere.list
sudo apt-get -y update
sudo apt-get -y install mesos=1.1.0-2.0.107.debian81
sudo bash -c "echo 192.168.33.50 > /etc/mesos-master/ip"
sudo bash -c "echo 192.168.33.50 > /etc/mesos-slave/ip"
sudo bash -c "echo docker,mesos > /etc/mesos-slave/containerizers"
sudo bash -c "echo /usr/bin/docker-1.7.0 > /etc/mesos-slave/docker"

# Start a bunch of services
sudo service zookeeper restart
sleep 5
(sudo service mesos-master stop || true)
(sudo service mesos-slave stop || true)

# Install Docker
sudo bash -c 'echo "deb http://http.debian.net/debian wheezy-backports main" > /etc/apt/sources.list.d/backports.list'
sudo apt-get install -y linux-image-amd64
curl -sSL https://get.docker.com/ | sh
sudo usermod -a -G docker vagrant

# Download a specific docker binary
# TODO: Skip the above?
sudo bash -c "curl -0 https://get.docker.com/builds/Linux/x86_64/docker-1.7.0 > /usr/bin/docker-1.7.0"
sudo chmod +x /usr/bin/docker-1.7.0

# Set up the docker registry
sudo mkdir -p /registry
sudo docker create -p 5000:5000 -v /registry:/tmp/registry-dev --name=registry registry:0.9.1
(sudo docker start registry || true)

# Start mesos
sudo service mesos-master start
sudo service mesos-slave start

# Install portainer dependencies
sudo apt-get install -y python-setuptools
sudo apt-get install -y python-dev
sudo easy_install pip
sudo pip install virtualenv
SCRIPT

Vagrant.configure("2") do |config|

  config.vm.box = "puppetlabs/debian-8.2-64-nocm"

  config.vm.synced_folder "./", "/opt/portainer"
  config.vm.network :private_network, ip: "192.168.33.50"

  # Configure the VM with 1024Mb of RAM and 2 CPUs
  config.vm.provider :virtualbox do |vb|
    vb.customize ["modifyvm", :id, "--memory", "1024"]
    vb.customize ["modifyvm", :id, "--cpus", "2"]
  end

  # ensure VM clock stays in sync with correct time zone
  config.vm.provision :shell, :inline => "sudo rm /etc/localtime && sudo ln -s /usr/share/zoneinfo/Europe/London /etc/localtime", run: "always"

  # Install all the things!
  config.vm.provision "shell", inline: $docker_setup
end

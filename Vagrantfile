# -*- mode: ruby -*-
# vi: set ft=ruby :

# Install docker
$docker_setup = <<SCRIPT
set -e

wget -q -O - http://get.docker.io/gpg | sudo apt-key add -
sudo bash -c "echo 'deb http://get.docker.io/ubuntu docker main' > /etc/apt/sources.list.d/docker.list"
sudo apt-get update -q
sudo apt-get install -q -y lxc-docker
sudo usermod -a -G docker vagrant
SCRIPT

Vagrant.configure("2") do |config|

  # Use the same base box as vagrant-web
  config.vm.box = "debian-73-x64-virtualbox-nocm"

  config.vm.synced_folder "./", "/opt/portainer"
  config.vm.network :private_network, ip: "192.168.33.50"

  # Configure the VM with 1024Mb of RAM and 2 CPUs
  config.vm.provider :virtualbox do |vb|
    vb.customize ["modifyvm", :id, "--memory", "1024"]
    vb.customize ["modifyvm", :id, "--cpus", "2"]
  end

  # Install all the things!
  config.vm.provision "shell", inline: $docker_setup
end

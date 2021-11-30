# -*- mode: ruby -*-
# vi: set ft=ruby :
Vagrant.configure("2") do |config|
  config.vm.provider "virtualbox" do |backend|
    backend.customize ["modifyvm", :id, "--groups", "/Asterisk (prototype)"]
    backend.memory = 512
    backend.cpus = 1
  end

  config.vm.define "asterisk" do |instance|
    instance.vm.provider :virtualbox do |backend|
      backend.name = "asterisk"
    end
    instance.vm.hostname = "asterisk"
    instance.vm.box = "ubuntu/trusty64"
    instance.vm.network "private_network", ip: "192.168.50.41"
    instance.vm.provision "shell", path: "bootstrap.sh", :args => ["192.168.50.41"]
  end
end

### Topology files for Vagrant and tests

These are required for Vagrant provisioning and tests configuration.

#### Limitations

Currently, there's a single, hardcoded topology (master, two replicas and 
a client). Network adresses and DNS resolver are hardcoded.

**TODO**: Generate the topology with Ansible.

**TODO2**: Replace Vagrant inline shell provisioning with Ansible.

**TODO3**: Use proper DNS names without hacking /etc/hosts.


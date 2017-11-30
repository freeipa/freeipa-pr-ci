# FreeIPA Pull Request CI

Scripts that are used by the PR CI testing infrastructure.

## Contributor's Guide

If you're looking for an overview of what the system looks like for
contributors, you can check out this [video](https://vimeo.com/228077191).

Slides from the video are also available in
[contributors_guide_slides.pdf](doc/contributors_guide_slides.pdf).

Update 2017-09-20: It is no longer necessary to open a PR against multiple
branches if code for different branches is the same. Backporting will be
handled by our tooling.
([Details](https://github.com/freeipa/freeipa-tools/pull/58))

## Setting up runner

### Prerequisites

#### Runner

- **Dedicated machine**: runners have some configuration and behaviour that's
  not desirable for a workstation. Virtual machine can be used if the
  hypervisor has support for nested virtualization.
- **Root access**: set up root access to the machine. This can be done
  with [ssh_config](https://linux.die.net/man/5/ssh_config),
  [ansible inventory parameters](https://docs.ansible.com/ansible/latest/intro_inventory.html#list-of-behavioral-inventory-parameters)
  or [ansible configuration](https://docs.ansible.com/ansible/latest/intro_configuration.html).
  (*Note*: please use `freeipa_pr_ci` key for root access if you have it)
- **Hostname**: short hostname is used as the runner identifier, please make
  sure it is unique.
- **Persistent configuration**: runner may be rebooted occassionally. All
  configuration including hostname and networking should persist after reboot.
- **Minimum specs**: 4 vCPUs, 8 GB RAM, 30 GB disk.
- **Operating system**: currently, only Fedora is supported.
- **Partitioning**: `/var/lib/libvirt/images` and `/root/.vagrant.d/` have to
  be on the *same* partition.

#### Other

- `ansible >= 2.3` on the control machine
- GitHub token with *Full control of private repositories* (Settings ->
  Personal access tokens)
- `freeipa_pr_ci` private key placed in `keys/`
- private keys in `keys/` have permissions set to 0600

### Development runner deployment

The development runner can be deployed to monitor any FreeIPA fork while
executing any FreeIPA PR CI fork (any owner and branch). This is useful for
testing and development purposes.

1. Create ansible inventory `ansible/hosts/runners`

   ```
   [runners_devel]
   2.3.4.5
   ```

2. Run the `prepare_devel_test_runners.yml` playbook, specify which repository
   should be monitored and which code repository and branch should be used to
   deploy the runner

   ```
   ansible-playbook \
     -i ansible/hosts/runners \
     ansible/prepare_devel_test_runners.yml
   ```

### "Production" Runner deployment

1. Create ansible inventory `ansible/hosts/runners`

   ```
   [runners]
   1.2.3.4
   ```

2. Run the `prepare_test_runners.yml` playbook

   ```
   ansible-playbook \
     -i ansible/hosts/runners \
     ansible/prepare_test_runners.yml
   ```

This will set up the runner machine with `prci` service, which is configured
to start at boot. The runner is periodically updated to use the latest code.
In the unfortunate event the update didn't execute successfully, the service
will enter a failed state. Re-running the above `ansible-playbook` command
from the up-to-date code should fix such issues.

### Side notes about deployment

#### Runner deployment automation

By default, ansible will prompt for API token and other variables. To fully
automate the deployment, you can pass the variables as arguments to the
`ansible-playbook` command with `-e key=value`. Arguments might be seen in
the following table. Availability of arguments is also mentioned in the table.

| Key                    | Value              | Production | Development |
| ---------------------- |------------------- | :--------: | :---------: |
| `github_token`         | GitHub API token   | x          | x           |
| `monitored_repo_owner` | FreeIPA repo owner |            | x           |
| `pr_ci_repo_owner`     | PR CI repo owner   |            | x           |
| `pr_ci_repo_branch`    | PR CI repo branch  |            | x           |

#### Monitoring runner activity

```bash
systemctl status prci
journalctl -fu prci
```

## User Guide

### Re-running tasks

You can use the `re-run` label to:

* re-run failing tasks: once the label is added, the tasks with status error
  or failure will be mark as unassigned, and later they will be run.

* New tasks were added to config file in the target branch:
  If the config file was changed in the target branch, the `re-run` label will
  create the missing tasks and will run them.

*Important*: If you are running it against your fork, you'll need to create
the label.

## Creating vagrant template box


1. Make sure you've configured `~/.config/atlas_box_uploader.yaml` to enable
   box upload to vagrantcloud.

   ```yaml
   url: https://vagrantcloud.com
   username: freeipa
   token: $TOKEN
   ```

2. If you're creating a brand new box that has no previous versions, go to
   vagrantcloud.com and create the box manually. Follow the
   convention of `freeipa/ci-$BRANCH_NAME-fXX`. You also need to create a first
   version of the box, e.g. `0.1.0` (it doesn't need to be released or
   uploaded).

3. Make sure correct variables for Fedora version are configured in
   `ansible/vars/fedora/`.

4. Run `create-box-template`

   This will create a vagrant box in `/tmp/$box_name/`. It will also be
   published on vagrantcloud.

## Developer Documentation

You can find the latest developer documentation in
[doc/README.md](doc/README.md).

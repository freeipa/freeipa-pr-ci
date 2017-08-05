# FreeIPA Pull Request CI

Scripts that are used by the PR CI testing infrastructure.

## Contributor's Guide

If you're looking for an overview of what the system looks like for
contributors, you can check out this [video](https://vimeo.com/228077191).

## Setting up runner

1. Create ansible inventory `ansible/hosts/runners`

   ```
   [runner]
   1.2.3.4
   ```

2. Place `freeipa_pr_ci` private key in `keys/`

   This is only necessary if you want to publish logs to fedorapople. To omit
   this step, specify `--skip-tags fedorapeople`.

3. Generate GitHub API token with permission 'Full control of private repositories'.

4. Run the `prepare_test_runners.yml` playbook

   ```
   ansible-playbook \
     -i ansible/hosts/runners \
     ansible/prepare_test_runners.yml
   ```

### Note on runner deployment automation

By default, ansible will prompt for API token and other variables. To fully
automate the deployment, you can pass the variables as arguments to the
`ansible-playbook` command with `-e key=value`. To find the variable names,
check the ansible playbooks.

### Setting up development runner

The development runner can be deployed to monitor any FreeIPA fork while
executing any FreeIPA PR CI fork (any owner and branch). This is useful for
testing and development purposes.

Set up the key as above and generate a GitHub token for your repository.

1. You need to configure the ssh connection to connect as root. There is
   some ways to do this, one of them is to configure your .ssh/config in
   someway like this:

   ```
   Host vmrunner
       User root
       HostName 2.3.4.5  # runner vm ip
   ```

2. Create ansible inventory `ansible/hosts/runners`

   ```
   [runner_devel]
   vmrunner  # runner vm hostname
   ```

3. Run the `prepare_devel_test_runners.yml` playbook, specify which repository
   should be monitored and which code repository and branch should be used to
   deploy the runner

   ```
   ansible-playbook \
     -i ansible/hosts/runners
     ansible/prepare_devel_test_runners.yml
   ```

## Creating vagrant template box

1. Run `create-box-template`

   This will create a vagrant box in `/tmp/$box_name/`.

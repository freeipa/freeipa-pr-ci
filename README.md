# FreeIPA Pull Request CI

Scripts that are used by the PR CI testing infrastructure.

## Setting up runner

1. Create `hosts` file

   ```
   [runner]
   1.2.3.4
   ```

2. Place `freeipa_pr_ci` private key in `keys/`

   This is only necessary if you want to publish logs to fedorapople. To omit 
   this step, specify `--skip-tags fedorapeople`.

3. Run the `prepare_test_runners.yml` playbook

   ```
   ansible-playbook \
     -i hosts \
     ansible/prepare_test_runners.yml
   ```

### Setting up localhost as runner

The playbook has to be executed as root and you don't need nested virtualization.

```
sudo ansible-playbook \
  -i ansible/hosts/runner_localhost \
  ansible/prepare_test_runners.yml \
  --skip-tags nested_virt
```

## Creating vagrant template box

1. Run `create-box-template`

   This will create a vagrant box in `/tmp/$box_name/`.

#!/usr/bin/env python

from __future__ import print_function

from base64 import b64decode
from os import listdir, path
from re import findall
from subprocess import PIPE, Popen

from appdirs import user_config_dir
import cmd2
from ruamel import yaml

from six.moves import input

# Python readline has completer delimiters that work for the Python shell,
# but we want to complete names that have dashes
import readline
readline.set_completer_delims(readline.get_completer_delims().replace('-', ''))


CONFIG_PATH = path.join(user_config_dir('dt-openshift-deploy', 'digitransit'),
                        'dt-openshift-deploy.yaml')
OS_TYPES = ('svc', 'dc', 'route')


class DeployShell(cmd2.Cmd, object):
    intro = 'Type help or ? to list commands.\n'

    def __init__(self, config):
        self.config = config
        super(DeployShell, self).__init__()
        self.prompt = self.colorize('(dt-openshift-deploy) ', 'bold')

    def oc_cmd(self, *args):
        '''Run oc with given arguments'''
        p = Popen((self.config['oc_path'],) + args, stderr=PIPE)
        if p.wait() != 0:
            errors = '\n'.join(p.stderr.readlines())
            if errors.find('provide credentials') != -1:
                print('You need to log in')
                return False
            else:
                print(errors)
        return True

    def preloop(self):
        self.do_status(None)
        print('\n')

    def target_complete(self, text='', line='', begidx=None, endidx=None):
        '''
        Complete first arg to OS types and second to available yamls of given type.
        '''
        spaces = len(findall(' ', line))
        if spaces < 2:
            choices = OS_TYPES
        elif spaces == 2:
            choices = dirswith(line.split()[1]) + ['all']
        else:
            choices = []
        return [x + ' ' for x in choices if x.startswith(text)]

    def do_status(self, arg):
        '''Get oc status (printed at startup)'''
        # TODO List currently deployed repository shas, and compare to :latest
        #      (or some other tag, if used) in Docker Hub
        # TODO Test that routes/services are actually reachable
        self.oc_cmd('status')

    def do_recreate(self, arg):
        '''recreate TYPE NAME

        Delete and create an OpenShift resource from files under subfolders.
        Files need to be named TYPE.yaml.

        NAME can be `all` to recreate all targets of given type

        Examples:
            recreate svc digitransit-proxy
            recreate dc all
        '''
        type, target = arg.split()
        if target == 'all':
            targets = dirswith(type)
        else:
            targets = [target]
        for t in targets:
            # TODO delete should take the target from the name field in yaml
            #      as that might not match the dir name
            # OpenShift (or oc) limits service names to 24 chars, but
            # other resources can be longer
            if type == 'svc' and not self.oc_cmd('delete', type, t[:24]):
                return
            elif not self.oc_cmd('delete', type, t):
                return
            if type == 'dc':
                # This also deletes istags
                self.oc_cmd('delete', 'is', t)

            self.oc_cmd('create', '-f', path.join(t, type + '.yaml'))

    complete_recreate = target_complete

    def do_deploy_image(self, arg):
        '''Deploy a new image from Docker Hub to OS registry.'''
        # TODO Should get the repositories (Docker image name) from within the yamls
        # TODO Hardcoded hsldevcom
        if arg == 'all':
            targets = dirswith(type)
        else:
            targets = [arg]
        for t in targets:
            self.oc_cmd('import-image', 'hsldevcom/' + t)

    def complete_deploy_image(self, text='', line='', begidx=None, endidx=None):
        choices = dirswith('dc') + ['all']
        return [x + ' ' for x in choices if x.startswith(text)]

    def do_login(self, arg):
        '''login USERNAME PASSWORD

        Login to OpenShift instance with the oc client (creating an OAuth token)
        '''
        username, password = arg.split()
        self.oc_cmd('login', '--username', username, '--password', password)

    def do_secrets(self, arg):
        '''
        secrets
            List all non-kubernets b64 encoded secrets
        secrets clear
            List cleartext secrets
        '''
        if arg == 'clear':
            clear = True
        else:
            clear = False

        p = Popen([self.config['oc_path'], 'get', 'secrets', '-o', 'yaml'],
                  stdout=PIPE)
        p.wait()
        result = yaml.safe_load(p.stdout)
        for secret in (r for r in result['items']
                       if not r['type'].startswith('kubernetes')):
            print(secret['metadata']['name'])
            for k, v in secret['data'].iteritems():
                if clear:
                    v = b64decode(v)
                print(' %s: %s' % (k, v))

    def complete_secrets(self, text='', line='', begidx=None, endidx=None):
        return ['clear']

    def do_new_secret(self, arg):
        '''new_secret NAME KEY VALUE'''
        name, key, value = arg.split()
        self.oc_cmd('create', 'secret', 'generic', name,
                    '--from-literal=' + key + '=' + value)

    def do_mem(self, arg):
        p = Popen([self.config['oc_path'], 'get', 'pods'], stdout=PIPE)
        p.wait()
        p.stdout.readline()
        print('{:<45} {:>12} {:>12} {:>12}'.format('POD', 'Used memory', 'Free memory', '+- swap/cache'))
        for pod in (x.split()[0] for x in p.stdout.readlines()):
            # Without -T the oc rsh will bork the shell (actually tty) echoing
            ps = Popen([self.config['oc_path'], 'rsh', '-T', pod,
                        'ps', 'vwx', '--sort', 'rss'],
                       stdout=PIPE)
            free = Popen([self.config['oc_path'], 'rsh', '-T', pod, 'free', '-m'],
                         stdout=PIPE)
            ps.wait()
            free.wait()
            ps.stdout.readline()
            free.stdout.readline()
            print('{:<45} {:>11}M {:>11}M {:>11}M'.format(
                pod,
                sum((int(x.split()[7]) for x in ps.stdout.readlines())) / 1000,
                free.stdout.readline().split()[3],
                free.stdout.readline().split()[3]))

    def do_eof(self, arg):
        print()  # Clear line, like when quitting with quit
        return True


def dirswith(filename):
    '''Get all directories containing given .yaml file.'''
    return sorted([x for x in listdir('.')
                   if (path.isdir(x) and
                       not x.startswith('.') and
                       path.exists(path.join(x, filename + '.yaml')))])


def read_config():
    config = {}
    if path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config.update(yaml.safe_load(f))
    return config


def save_config(config):
    if not path.exists(path.dirname(CONFIG_PATH)):
        from os import makedirs
        makedirs(path.dirname(CONFIG_PATH))
    with open(CONFIG_PATH, 'w') as f:
        yaml.safe_dump(config, f)


def main():
    config = read_config()
    if 'oc_path' not in config:
        config['oc_path'] = path.expanduser(input("Enter path to oc binary: "))
        save_config(config)

    DeployShell(config).cmdloop()


if __name__ == '__main__':
    main()

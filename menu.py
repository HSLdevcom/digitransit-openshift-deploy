#!/usr/bin/env python

from __future__ import print_function

from base64 import b64decode
from glob import iglob
from os import listdir, path
from re import findall, search
from subprocess import PIPE, Popen

from appdirs import user_config_dir
from blessings import Terminal
import cmd2
from ruamel import yaml
from jinja2 import FileSystemLoader, Environment
from six.moves import input

# Python readline has completer delimiters that work for the Python shell,
# but we want to complete names that have dashes
import readline
readline.set_completer_delims(readline.get_completer_delims().replace('-', ''))

CONFIG_PATH = path.join(user_config_dir('dt-openshift-deploy', 'digitransit'),
                        'dt-openshift-deploy.yaml')
OS_TYPES = ('svc', 'dc', 'route')
term = Terminal()

class DeployShell(cmd2.Cmd, object):
    intro = 'Type help or ? to list commands.\n'

    def __init__(self, config):
        self.config = config
        super(DeployShell, self).__init__()
        self.project = self.get_project_name(self.oc_query('project'))
        self.set_prompt()

        TEMPLATES_DIR = path.abspath(path.dirname(__file__))
        loader = FileSystemLoader(TEMPLATES_DIR)
        self.env = Environment(loader=loader)
        self.projectConfig = {'dev':read_yaml(file_path('dev.yaml')), 'test':read_yaml(file_path('test.yaml'))}

    def set_prompt(self):
        self.prompt = self.colorize('(dt-openshift-deploy@' + (self.project or 'not logged in') + ') ', 'bold')

    def oc_cmd(self, *args):
        '''Run oc with given arguments and print possible error and return false if not logged in'''
        process = Popen((self.config['oc_path'],) + args, stderr=PIPE)
        errors = self.get_errors(process)
        if errors:
            self.print_oc_error(errors);

        if self.is_login_error(errors):
            return False

        return True

    def get_errors(self, process):
        if process.wait() != 0:
            errors = '\n'.join(process.stderr.readlines())
            return errors
        return None

    def print_oc_error(self, errors):
        if self.is_login_error(errors):
            print('you need to log in')
        else:
            print(errors)

    def is_login_error(self, error):
        '''Check if login error'''
        return error != None and error.find('provide credentials') != -1

    def oc_query(self, *args):
        '''Run oc with given args and return output of None if error'''
        process = Popen((self.config['oc_path'],) + args, stderr=PIPE, stdout=PIPE)
        errors = self.get_errors(process)
        if errors:
            self.print_oc_error(errors);
            return None
        return '\n'.join(process.stdout.readlines())

    def pipe_to_oc(self, content, *args):
        '''Run oc with given args and return output of None if error'''

        p = Popen((self.config['oc_path'],) + args, stdin=PIPE, stderr=PIPE, stdout=PIPE)
        stdout, stderr = p.communicate(input=content)

        if stderr:
            self.print_oc_error(stderr);

            if self.is_login_error(stderr):
                return False


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

    def get_project_name(self, out):
        '''Parse project name project'''
        if out is not None:
            m = search('Using project "(.*?)"', out)
            return m.group(1)
        return None

    def do_project(self, *arg):
        '''Display or set current project'''
        if len(arg) == 1 and arg[0]: #set
            p = self.oc_query('project', arg[0]);
            if p is not None:
                print(p)
                self.project = arg[0]
                self.set_prompt()
        else:
            project = self.oc_query('project')
            print(project)

    def render(self, template):
        '''renders template with env based props'''
        template_file = self.env.get_template(template)
        return template_file.render(self.projectConfig[self.project]);

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

    def do_apply(self, arg):
        '''apply TYPE NAME

        Edit an OS resource in place.

        NAME can be `all` to apply all targets of given type

        Examples:
            apply svc digitransit-proxy
            apply dc all
        '''

        dryRun = False

        parts = arg.split()
        if len(parts) == 2:
            type, target = parts
        else:
            type, target, dry = parts
            if dry == '--dry':
                dryRun = True

        if target == 'all':
            targets = dirswith(type)
        else:
            targets = [target]
        for t in targets:
            template = path.join(t, type + '.yaml')
            content = self.render(template);
            if dryRun:
                print(content)
            else:
                self.pipe_to_oc(content, 'apply', '-f', '-');
            #self.oc_cmd('apply', '-f', path.join(t, type + '.yaml'))

    complete_apply = target_complete

    def do_deploy_image(self, arg):
        '''Deploy a new image from Docker Hub to OS registry.'''
        # TODO Should get the repositories (Docker image name) from within the yamls
        # TODO Hardcoded hsldevcom
        if arg == 'all':
            targets = get_target_names('is')
        else:
            targets = [arg]
        for t in targets:
            self.oc_cmd('import-image', 'hsldevcom/' + t)

    def complete_deploy_image(self, text='', line='', begidx=None, endidx=None):
        choices = get_target_names('is') + ['all']
        return [x + ' ' for x in choices if x.startswith(text)]

    def do_login(self, arg):
        '''login USERNAME PASSWORD

        Login to OpenShift instance with the oc client (creating an OAuth token)
        '''
        username, password = arg.split()
        self.oc_cmd('login', '--username', username, '--password', password)
        self.project = self.get_project_name(self.oc_query('project'))
        self.set_prompt()

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

    def do_top(self, arg):
        p = Popen([self.config['oc_path'], 'get', 'pods'], stdout=PIPE)
        p.wait()
        p.stdout.readline()
        pods = [x.split()[0] for x in p.stdout if x.split()[2] == 'Running']
        # Without -T the oc rsh will bork the shell (actually tty) echoing
        stats = {}
        for pod in pods:
            print("Opening pipe to %s" % pod)
            stats[pod] = Popen([self.config['oc_path'], 'rsh', '-T', pod,
                                'vmstat', '-n', '-SM', '4'], stdout=PIPE)
        for pod in pods:
            print("Reading stats from %s" % pod)
            stats[pod].stdout.readline()
            stats[pod].stdout.readline()
        with term.fullscreen():
            format = '{:>5} {:>5} {:>5} {:>5}   {:>4} {:>6} {:>4} {:>4}'
            print(term.move(0, 0))
            print(format.format('used', 'free', 'buff', 'cache', 'user', 'system', 'idle', 'wait'))
            while True:
                print(term.move(1, 0))
                ps = {pod: Popen([self.config['oc_path'], 'rsh', '-T', pod,
                                  'ps', 'vwx', '--sort', 'rss'],
                                 stdout=PIPE)
                      for pod in pods}
                for pod in pods:
                    print(pod)
                    ps[pod].stdout.readline()
                    s = stats[pod].stdout.readline().split()
                    try:
                        print(format.format(
                            sum((int(x.split()[7]) for x in ps[pod].stdout)) / 1000,
                            s[3], s[4], s[5], s[12], s[13], s[14], s[15]))
                    except:
                        print(s)
                        from time import sleep
                        sleep(10)
        print('Stopping')
        for p in stats:
            p.terminate()

    def do_eof(self, arg):
        print()  # Clear line, like when quitting with quit
        return True

def get_target_names(target_type):
    if target_type == 'dc':
        kind = 'DeploymentConfig'
    elif target_type == 'is':
        kind = 'ImageStream'
    elif target_type == 'svc':
        kind = 'Service'
    elif target_type == 'route':
        kind = 'Route'

    results = []
    for yamlfile in iglob('*/*.yaml'):
        with open(yamlfile) as f:
            y = yaml.safe_load(f)
            if y['kind'] == 'List':
                items = y['items']
            else:
                items = [y, ]
            for i in items:
                if i['kind'] == kind:
                    results.append(i['metadata']['name'])
    return results

def dirswith(filename):
    '''Get all directories containing given .yaml file.'''
    return sorted([x for x in listdir('.')
                   if (path.isdir(x) and
                       not x.startswith('.') and
                       path.exists(path.join(x, filename + '.yaml')))])

def read_yaml(file):
    config = {}
    if path.exists(file):
        with open(file) as f:
            config.update(yaml.safe_load(f))
    return config

def file_path(name):
    return path.join(path.abspath(path.dirname(__file__)),name)

def read_config():
    return read_yaml(CONFIG_PATH)

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

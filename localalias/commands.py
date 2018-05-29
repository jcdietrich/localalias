"""Command definitions."""

from abc import ABCMeta, abstractmethod
import json
import os
import subprocess as sp
import tempfile
import time

from pygments import highlight
from pygments.lexers import BashLexer
from pygments.formatters import TerminalFormatter

from localalias import errors
from localalias import utils
from localalias.utils import log


class Command(metaclass=ABCMeta):
    """Abstract base command class.

    To use a command, the corresponding command class should be used to build a command instance.
    A command instance is a callable object.

    Args:
        args (argparse.Namespace): command-line arguments.
    """
    LOCALALIAS_DB_FILENAME = '.localalias'

    def __init__(self, args):
        self.args = args
        try:
            with open(self.LOCALALIAS_DB_FILENAME, 'r') as f:
                self.alias_dict = json.load(f)
        except FileNotFoundError as e:
            self.alias_dict = {}

        log.logger.vdebug('Existing Aliases: {}'.format(self.alias_dict))

    def commit(self):
        """Saves alias changes to local database."""
        log.logger.debug('Committing changes to local database: {}'.format(self.LOCALALIAS_DB_FILENAME))
        with open(self.LOCALALIAS_DB_FILENAME, 'w') as f:
            json.dump(self.alias_dict, f)

    @abstractmethod
    def __call__(self):
        log.logger.debug('Running {} command.'.format(self.__class__.__name__))


class Execute(Command):
    def execute(self, alias=None):
        """Evaluates and executes the command string corresponding with the given alias.

        Args:
            alias (optional): The alias to edit. If not given, this function uses the alias defined
                at instance creation time.
        """
        if alias is None:
            alias = self.args.alias

        log.logger.debug('Executing command string mapped to "{}" local alias.'.format(alias))
        cmd_args = ' '.join(self.args.cmd_args)
        sp.call(['zsh', '-c', 'set -- {}\n{}'.format(cmd_args, self.alias_dict[alias])])

    def __call__(self):
        super().__call__()
        if self.args.alias not in self.alias_dict:
            raise errors.AliasNotDefinedError(self.args.alias)
        self.execute()


class Show(Command):
    def show(self, alias):
        """Print alias and alias command definition to stdout."""
        alias_cmd_string = self.alias_dict[alias]
        if '\n' in alias_cmd_string:
            show_output = '{0}() {{\n\t{1}\n}}'.format(alias, alias_cmd_string.replace('\n', '\n\t'))
        else:
            show_output = '{0}() {{ {1}; }}'.format(alias, alias_cmd_string)

        if self.args.color:
            log.logger.debug('Showing colorized output.')
            final_output = highlight(show_output, BashLexer(), TerminalFormatter())
        else:
            log.logger.debug('Showing normal output.')
            final_output = show_output

        print(final_output)

    def show_all(self):
        """Prints all defined alias definitions to stdout."""
        log.logger.debug('Running show command for all defined aliases.')
        for i, alias in enumerate(sorted(self.alias_dict)):
            self.show(alias)
            if i < len(self.alias_dict) - 1:
                print()

    def __call__(self):
        super().__call__()
        if not self.alias_dict:
            raise errors.AliasNotDefinedError()

        if self.args.alias and self.args.alias not in self.alias_dict:
            raise errors.AliasNotDefinedError(self.args.alias)

        if self.args.alias is None:
            self.show_all()
        else:
            self.show(self.args.alias)


class Edit(Command):
    def edit_alias(self, alias=None):
        """Opens up alias definition using temp file in $EDITOR for editing.

        Args:
            alias (optional): The alias to edit. If not given, this function uses the alias defined
                at instance creation time.

        Returns (str):
            Contents of temp file after $EDITOR closes.
        """
        if alias is None:
            alias = self.args.alias

        tf = tempfile.NamedTemporaryFile(prefix='{}.'.format(alias),
                                         suffix='.zsh',
                                         mode='w',
                                         delete=False)
        if alias in self.alias_dict:
            tf.write(self.alias_dict[alias])
        tf.close()

        if 'EDITOR' in os.environ:
            editor = os.environ['EDITOR']
            log.logger.debug('Editor set to $EDITOR: {}'.format(editor))
        else:
            editor = 'vim'
            log.logger.debug('Editor falling back to default: {}'.format(editor))

        editor_cmd_list = [editor, tf.name]
        try:
            sp.check_call(editor_cmd_list)
        except sp.CalledProcessError as e:
            raise errors.LocalAliasError('Failed to open editor using: {}'.format(editor_cmd_list))

        tf = open(tf.name, 'r')
        edited_alias_cmd_string = tf.read()
        tf.close()
        os.unlink(tf.name)

        return edited_alias_cmd_string.strip()

    def __call__(self):
        super().__call__()
        if self.args.alias and self.args.alias not in self.alias_dict:
            raise errors.AliasNotDefinedError(self.args.alias)

        msg_fmt = 'Edited local alias "{}".'
        if self.args.alias is None:
            log.logger.debug('Running edit command for all defined aliases.')
            for alias in sorted(self.alias_dict):
                self.alias_dict[alias] = self.edit_alias(alias)
                log.logger.info(msg_fmt.format(alias))
        else:
            self.alias_dict[self.args.alias] = self.edit_alias()
            log.logger.info(msg_fmt.format(self.args.alias))
        self.commit()


class Remove(Show):
    def __call__(self):
        Command.__call__(self)
        if self.args.alias and self.args.alias not in self.alias_dict:
            raise errors.AliasNotDefinedError(self.args.alias)

        if not self.alias_dict:
            raise errors.AliasNotDefinedError()

        if self.args.alias is None:
            log.logger.debug('Prompting to destroy local alias database.')
            prompt = 'Remove all local aliases defined in this directory? (y/n): '
            y_or_n = utils.getch(prompt)
            if y_or_n == 'y':
                self.alias_dict = {}
                print()
                log.logger.info('Done. The local alias database has been removed.')
            else:
                print()
                log.logger.info('OK. Nothing has been done.')
                return
        else:
            self.alias_dict.pop(self.args.alias)
            log.logger.info('Removed local alias "{}".'.format(self.args.alias))

        self.commit()

        if self.alias_dict:
            print()
            self.show_all()
        else:
            log.logger.debug('Removing {}.'.format(self.LOCALALIAS_DB_FILENAME))
            os.remove(self.LOCALALIAS_DB_FILENAME)


class Add(Edit):
    def __call__(self):
        Command.__call__(self)
        if self.args.alias in self.alias_dict:
            msg_fmt = 'Local alias "{}" is already defined. Running edit command.'
            log.logger.info(msg_fmt.format(self.args.alias))
            time.sleep(1)

        self.alias_dict[self.args.alias] = self.edit_alias()
        log.logger.info('Added local alias "{}".'.format(self.args.alias))
        self.commit()

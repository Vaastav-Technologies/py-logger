#!/usr/bin/env python3
# coding=utf-8


"""
Logger interfaces for Logger configurators.
"""
import logging
import os
from abc import abstractmethod
from typing import Protocol, override, cast
from collections.abc import Callable

from vt.utils.logging.lib_logging import VT_ALL_LOG_ENV_VAR
from vt.utils.logging.lib_logging.std_log.base import DirectStdAllLevelLogger
from vt.utils.logging.lib_logging.std_log.utils import get_first_non_none


class LoggerConfigurator(Protocol):
    """
    Stores configuration information to configure the std python logger.
    """

    @abstractmethod
    def configure(self, logger: logging.Logger) -> DirectStdAllLevelLogger:
        """
        Configure the std python logger for various formatting quick-hands.

        :param logger: std python logger
        :return: A configured All level logging std python logger.
        """
        pass

    @abstractmethod
    def clone_with(self, **kwargs) -> 'LoggerConfigurator':
        """
        :param kwargs: overriding keyword args.
        :return: a new instance of the ``LoggerConfigurator`` with the provided overrides.
        """
        ...


class HasUnderlyingConfigurator(Protocol):
    """
    A configurator which has other configurators underneath it. Majorly used to decorate configurators to add
    functionalities to them.
    """

    @property
    @abstractmethod
    def underlying_configurator(self) -> LoggerConfigurator:
        """
        :return: The underlying logger configurator which is decorated by this configurator.
        """
        ...


class LevelTarget[T](Protocol):
    """
    Permits levels to be set.
    """

    @property
    @abstractmethod
    def level(self) -> T:
        """
        :return: current level.
        """
        ...

    @abstractmethod
    def set_level(self, new_level: T) -> T:
        """
        Sets new level.

        :param new_level: sets to this level.
        :return: the old level.
        """
        ...


class LevelLoggerConfigurator[T](LevelTarget[T], LoggerConfigurator, Protocol):
    """
    A logger configurator which allows setting levels from outside of it.
    """
    pass


class SupplierLoggerConfigurator[T](LoggerConfigurator, HasUnderlyingConfigurator):

    def __init__(self, level_supplier: Callable[[], T], configurator: LevelLoggerConfigurator[T]):
        """
        Configurator that configures loggers as per the level supplied by the ``level_supplier``.

        :param level_supplier: a supplier to supply level.
        :param configurator: underlying configurator.
        """
        self.level_supplier = level_supplier
        self.configurator = configurator

    def configure(self, logger: logging.Logger) -> DirectStdAllLevelLogger:
        final_level = self.level_supplier()
        self.configurator.set_level(final_level)
        return self.configurator.configure(logger)

    @override
    @property
    def underlying_configurator(self) -> LoggerConfigurator:
        return self.configurator

    @override
    def clone_with(self, **kwargs) -> 'SupplierLoggerConfigurator':
        """
        kwargs:
            ``level_supplier`` - a supplier to supply level.

            ``configurator`` - underlying configurator.
        :return: a new ``SupplierLoggerConfigurator``.
        """
        level_supplier = kwargs.pop('level_supplier', self.level_supplier)
        configurator = kwargs.pop('configurator', self.configurator)
        return SupplierLoggerConfigurator(level_supplier, configurator)


class ListLoggerConfigurator[T](LoggerConfigurator, HasUnderlyingConfigurator):
    DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE = get_first_non_none

    def __init__(self, level_list: list[T | None], configurator: LevelLoggerConfigurator,
                 level_pickup_strategy=DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE):
        """
        Picks up the first non ``None`` level from the supplied ``level_list`` to configure the logger underneath.

        * Examples:

          * supplied ``level_list`` cannot be ``None``:

            >>> ListLoggerConfigurator(None, # noqa: as level_list is deliberately passed as None
            ...     None) # noqa: as configurator is unused and passed as None
            Traceback (most recent call last):
            ValueError: Level list must not be None.

        :param level_list: list of log levels which may contain ``None``. First non-``None`` value
            is picked-up by default for logger configuration.
        :param configurator: configurator which is decorated by this logger-configurator.
        :param level_pickup_strategy: pick up a level from the list of levels supplied in ``level_list``. Default is
            to pick up the first non-``None`` level. ``DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE``.
        """
        if level_list is None:
            raise ValueError("Level list must not be None.")
        self._level_list = level_list
        self.configurator = configurator
        self.level_pickup_strategy = level_pickup_strategy

    def configure(self, logger: logging.Logger) -> DirectStdAllLevelLogger:
        final_level = self.level_pickup_strategy(self.level_list)
        self.configurator.set_level(final_level)
        return self.configurator.configure(logger)

    @override
    @property
    def underlying_configurator(self) -> LoggerConfigurator:
        return self.configurator

    @property
    def level_list(self) -> list[T | None]:
        return self._level_list

    @override
    def clone_with(self, **kwargs) -> 'ListLoggerConfigurator[T]':
        """
        kwargs:
            ``level_list`` - list of log levels which may contain ``None``. First non-``None`` value is picked-up by
            default for logger configuration.

            ``configurator`` - configurator which is decorated by this logger-configurator.

            ``level_pickup_strategy`` - pick up a level from the list of levels supplied in ``level_list``.
            Default is to pick up the first non-``None`` level. ``DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE``.
        :return: a new ``ListLoggerConfigurator``.
        """
        level_list = kwargs.pop('level_list', self.level_list.copy())
        configurator = kwargs.pop('configurator', self.configurator)
        level_pickup_strategy = kwargs.pop('level_pickup_strategy', self.level_pickup_strategy)
        return ListLoggerConfigurator[T](level_list, configurator, level_pickup_strategy)


class EnvListLC[T](ListLoggerConfigurator):
    DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE = ListLoggerConfigurator.DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE

    def __init__(self, env_list: list[str], configurator: LevelLoggerConfigurator[T],
                 level_pickup_strategy=DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE):
        """
        This logger configurator can be used to configure log level using values supplied from environment variables.
        Default behavior is to pick up the first passed environment variable value. Designed to process log level from
        multiple environment variables and hence has a precedence order to the values form environment variables. The
        first environment variable value takes highest precedence and then the precedence diminishes.

        :param env_list: list of environment variables. Default behavior is to take precedence in decreasing order.
        :param configurator: underlying logger configurator.
        :param level_pickup_strategy: strategy to pick-up level from a supplied list of levels. Default is to pick up
            the first supplied, then next and then so on.
        """
        super().__init__([], configurator, level_pickup_strategy)
        self._env_list = env_list

    @property
    def env_list(self) -> list[str]:
        return self._env_list

    @override
    @property
    def level_list(self) -> list[T | None]:
        return [cast(T | None, os.getenv(e)) for e in self.env_list]

    @override
    def clone_with(self, **kwargs) -> 'EnvListLC[T]':
        """
        kwargs:
            ``env_list`` - list of environment variables. Default behavior is to take precedence in decreasing order.

            ``configurator`` - configurator which is decorated by this logger-configurator.

            ``level_pickup_strategy`` - pick up a level from the list of levels supplied in ``level_list``. Default is
            to pick up the first non-``None`` level. ``DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE``.
        :return: a new ``EnvListLC``.
        """
        env_list = kwargs.pop('env_list', self.env_list.copy())
        configurator = kwargs.pop('configurator', self.configurator)
        level_pickup_strategy = kwargs.pop('level_pickup_strategy', self.level_pickup_strategy)
        return EnvListLC[T](env_list, configurator, level_pickup_strategy)

    def clone_with_envs(self, *envs: str, low_precedence: bool = False) -> 'EnvListLC[T]':
        """
        Clone the current environment list level logger configurator with some extra environment variables. May be used
        in scenarios when a certain module needs a Loger configurator dependent on the environment variables of another
        logger configurator and wants to include its own environment variable as well in the mix.

        For e.g. the `push-pull-prep` project has its logger configurator to heed to ``ENV_PPP`` environment variable
        and `push-pull-prep.some_other_module.py` needs to support ``ENV_PPP.SOM`` environment variable along with the
        parent module (`push-pull-prep`'s) environment variable (``ENV_PPP``). Then it can do so like this:

        Examples:

        * `push-pull-prep`'s environment variable logger configurator:

        >>> ppp_lc = EnvListLC(['ENV_PPP'],
        ...     None) # noqa: as configurator is unused and passed as None
        >>> assert ['ENV_PPP'] == ppp_lc.env_list

        * `push-pull-prep.some_other_module.py`'s environment variable logger configurator, which builds upon the
        `push-pull-prep`'s environment variable logger configurator. It can add its own environment variable
        ``ENV_PPP.SOM`` and by default that takes the highest precedence:

        >>> som_lc = ppp_lc.clone_with_envs('ENV_PPP.SOM')
        >>> assert ['ENV_PPP.SOM', 'ENV_PPP'] == som_lc.env_list
        >>> assert ['ENV_PPP'] == ppp_lc.env_list # no change to the original logger configurator's env list.

        * Add multiple env vars:

        >>> som_lc = ppp_lc.clone_with_envs('SUMO', 'ENV_PPP.SOM') # multiple env vars can be registered.
        >>> assert ['SUMO', 'ENV_PPP.SOM', 'ENV_PPP'] == som_lc.env_list
        >>> assert ['ENV_PPP'] == ppp_lc.env_list # no change to the original logger configurator's env list.

        * Add vars with lower precedence than the env vars of the original or parent logger configurator by setting
        ``low_precedence=True``:

        >>> som_lc = ppp_lc.clone_with_envs('SUMO', 'ENV_PPP.SOM', low_precedence=True)
        >>> assert ['ENV_PPP', 'SUMO', 'ENV_PPP.SOM'] == som_lc.env_list
        >>> assert ['ENV_PPP'] == ppp_lc.env_list # no change to the original logger configurator's env list.

        :param envs: extra environment variables which need to be introduced over and above the original logger
            configurator's own env vars.
        :param low_precedence: the extra introduced envs mostly prepend the original logger configurator's env vars and
            thus have a higher precedence than them. Setting this param as ``True`` makes the extra introduced env vars
            append (not prepend) the original logger configurator's env vars and thus keeps them at a lower precedence
            than the original logger configurator's env vars.
        :return: new logger configurator with extra newly introduced env vars.
        """
        _env_list = self.env_list.copy()
        if low_precedence:
            _env_list.extend(envs)
        else:
            _env_list = list(envs) + _env_list
        return self.clone_with(env_list=_env_list)


class VTEnvListLC[T](EnvListLC[T]):
    DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE = EnvListLC.DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE

    def __init__(self, env_list: list[str], configurator: LevelLoggerConfigurator[T],
                 level_pickup_strategy=DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE, all_log_env_var: str = VT_ALL_LOG_ENV_VAR):
        """
        This logger configurator can be used to configure log level using values supplied from environment variables.
        Default behavior is to pick up the first passed environment variable value. Designed to process log level from
        multiple environment variable values and hence has a precedence order to the values from environment variables.
        The first environment variable value takes highest precedence and then the precedence diminishes. Environment
        variable ``VT_ALL_LOG`` is always appended to ``env_list`` so that if no environment variable is registered
        then at least this one is registered.

        :param env_list: list of environment variables. Default behavior is to take precedence in decreasing order.
        :param configurator: underlying logger configurator.
        :param level_pickup_strategy: strategy to pick-up level from a supplied list of levels. Default is to pick up
            the first supplied, then next and then so on.
        :param all_log_env_var: Environment variable which, by default, will be checked last to get the logging levels.
        """
        env_list.append(all_log_env_var)
        super().__init__(env_list, configurator, level_pickup_strategy)

    @override
    def clone_with(self, **kwargs) -> 'VTEnvListLC[T]':
        """
        kwargs:
            ``env_list`` - list of environment variables. Default behavior is to take precedence in decreasing order.

            ``configurator`` - configurator which is decorated by this logger-configurator.

            ``level_pickup_strategy`` - pick up a level from the list of levels supplied in ``level_list``. Default is
            to pick up the first non-``None`` level. ``DEFAULT_LEVEL_PICKUP_FIRST_NON_NONE``.
        :return: a new ``VTEnvListLC``.
        """
        level_list = kwargs.pop('env_list', self.env_list.copy())
        configurator = kwargs.pop('configurator', self.configurator)
        level_pickup_strategy = kwargs.pop('level_pickup_strategy', self.level_pickup_strategy)
        return VTEnvListLC[T](level_list, configurator, level_pickup_strategy)

""" Viomi Vacumm """
import logging
import math
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_TOKEN,
)

from .vacuum import ViomiVacuum

_LOGGER = logging.getLogger(__name__)
DOMAIN = "viomi_vacuum"
DOMAINS = ["vacuum"]

async def async_setup(hass: HomeAssistant, hass_config: dict):
    """Set up the Viomi Vacumm component."""

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """ Update Optioins if available """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Support Viomi Vacumm."""

    hass.data.setdefault(DOMAIN, {})

    # migrate data (also after first setup) to options
    if entry.data:
        hass.config_entries.async_update_entry(entry, data={},
                                               options=entry.data)

    # add update handler
    if not entry.update_listeners:
        entry.add_update_listener(async_update_options)

    # init setup for each supported domains
    for platform in DOMAINS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(
            entry, platform))

    return True

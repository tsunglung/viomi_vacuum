"""Support for the Xiaomi/Viomi vacuum cleaner robot."""
# pylint: disable=import-error
import asyncio
from functools import partial
import logging


from miio import DeviceException, RoborockVacuum
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.components.vacuum import (
    ATTR_CLEANED_AREA,
    DOMAIN,
    PLATFORM_SCHEMA,
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RETURNING,
    VacuumEntityFeature,
    StateVacuumEntity,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_NAME,
    CONF_TOKEN,
    STATE_OFF,
    STATE_ON,
)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

ERROR_CODES = {
    500: "Radar timed out",
    501: "Wheels stuck",
    502: "Low battery",
    503: "Dust bin missing",
    508: "Uneven ground",
    509: "Cliff sensor error",
    510: "Collision sensor error",
    511: "Could not return to dock",
    512: "Could not return to dock",
    513: "Could not navigate",
    514: "Vacuum stuck",
    515: "Charging error",
    516: "Mop temperature error",
    521: "Water tank is not installed",
    522: "Mop is not installed",
    525: "Insufficient water in water tank",
    527: "Remove mop",
    528: "Dust bin missing",
    529: "Mop and water tank missing",
    530: "Mop and water tank missing",
    531: "Water tank is not installed",
    2101: "Unsufficient battery, continuing cleaning after recharge",
    2103: "Charging",
    2105: "Fully charged",
}

DEFAULT_NAME = "Viomi Vacuum cleaner STYJ02YM"
DATA_KEY = "vacuum.viomi"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_TOKEN): vol.All(str, vol.Length(min=32, max=32)),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

VACUUM_SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids})
SERVICE_CLEAN_ZONE = "xiaomi_clean_zone"
SERVICE_CLEAN_POINT = "xiaomi_clean_point"
ATTR_ZONE_ARRAY = "zone"
ATTR_ZONE_REPEATER = "repeats"
ATTR_POINT = "point"
SERVICE_SCHEMA_CLEAN_ZONE = VACUUM_SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_ZONE_ARRAY): vol.All(
            list,
            [
                vol.ExactSequence(
                    [vol.Coerce(float), vol.Coerce(float), vol.Coerce(float), vol.Coerce(float)]
                )
            ],
        ),
        vol.Required(ATTR_ZONE_REPEATER): vol.All(
            vol.Coerce(int), vol.Clamp(min=1, max=3)
        ),
    }
)
SERVICE_SCHEMA_CLEAN_POINT = VACUUM_SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_POINT): vol.All(
            vol.ExactSequence(
                [vol.Coerce(float), vol.Coerce(float)]
            )
        )
    }
)
SERVICE_TO_METHOD = {
    SERVICE_CLEAN_ZONE: {
        "method": "async_clean_zone",
        "schema": SERVICE_SCHEMA_CLEAN_ZONE,
    },
    SERVICE_CLEAN_POINT: {
        "method": "async_clean_point",
        "schema": SERVICE_SCHEMA_CLEAN_POINT,
    }
}

FAN_SPEEDS = {"Silent": 0, "Standard": 1, "Medium": 2, "Turbo": 3}


SUPPORT_XIAOMI = (
    VacuumEntityFeature.STATE
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.SEND_COMMAND
    | VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.START
)


STATE_CODE_TO_STATE = {
    0: STATE_IDLE,
    1: STATE_IDLE,
    2: STATE_PAUSED,
    3: STATE_CLEANING,
    4: STATE_RETURNING,
    5: STATE_DOCKED,
    6: STATE_CLEANING,  # Vacuum & Mop
    7: STATE_CLEANING   # Mop only
}

ALL_PROPS = ["run_state", "mode", "err_state", "battary_life", "box_type", "mop_type", "s_time",
            "s_area", "suction_grade", "water_grade", "remember_map",
            "has_map", "is_mop", "has_newmap"]


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Import Viomi configuration from YAML."""
    _LOGGER.warning(
        "Loading Viomi Vacuum via platform setup is deprecated; Please remove it from your configuration"
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config,
        )
    )


async def async_setup_entry(hass, config, async_add_entities):
    """Set up the Xiaomi vacuum cleaner robot platform."""
    if DATA_KEY not in hass.data:
        hass.data[DATA_KEY] = {}
    if config.data.get(CONF_HOST, None):
        host = config.data[CONF_HOST]
        token = config.data[CONF_TOKEN]
    else:
        host = config.options[CONF_HOST]
        token = config.options[CONF_TOKEN]
    name = config.title

    # Create handler
    _LOGGER.info("Initializing with host %s (token %s...)", host, token[:5])
    vacuum = RoborockVacuum(host, token)

    mirobo = ViomiVacuum(name, vacuum, token)
    hass.data[DATA_KEY][host] = mirobo

    async_add_entities([mirobo], update_before_add=True)

    async def async_service_handler(service):
        """Map services to methods on MiroboVacuum."""
        method = SERVICE_TO_METHOD.get(service.service)
        params = {
            key: value for key, value in service.data.items() if key != ATTR_ENTITY_ID
        }
        entity_ids = service.data.get(ATTR_ENTITY_ID)

        if entity_ids:
            target_vacuums = [
                vac
                for vac in hass.data[DATA_KEY].values()
                if vac.entity_id in entity_ids
            ]
        else:
            target_vacuums = hass.data[DATA_KEY].values()

        update_tasks = []
        for vacuum in target_vacuums:
            await getattr(vacuum, method["method"])(**params)

        for vacuum in target_vacuums:
            update_coro = vacuum.async_update_ha_state(True)
            update_tasks.append(update_coro)

        if update_tasks:
            await asyncio.wait(update_tasks)

    for vacuum_service in SERVICE_TO_METHOD:
        schema = SERVICE_TO_METHOD[vacuum_service].get("schema", VACUUM_SERVICE_SCHEMA)
        hass.services.async_register(
            DOMAIN, vacuum_service, async_service_handler, schema=schema
        )


class ViomiVacuum(StateVacuumEntity):
    """Representation of a Viomi Vacuum cleaner robot."""

    def __init__(self, name, vacuum, token):
        """Initialize the Viomi vacuum cleaner robot handler."""
        self._name = name
        self._vacuum = vacuum
        self._unique_id = token

        self._last_clean_point = None

        self.vacuum_state = None
        self._available = False

    @property
    def unique_id(self):
        """Return the entity unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the status of the vacuum cleaner."""
        if self.vacuum_state is not None:
            # The vacuum reverts back to an idle state after erroring out.
            # We want to keep returning an error until it has been cleared.

            try:
                return STATE_CODE_TO_STATE[int(self.vacuum_state['run_state'])]
            except KeyError:
                _LOGGER.error(
                    "STATE not supported, state_code: %s",
                    self.vacuum_state['run_state'],
                )
                return None
        return None

    @property
    def battery_level(self):
        """Return the battery level of the vacuum cleaner."""
        if self.vacuum_state is not None:
            return self.vacuum_state['battary_life']
        return 'Unknown'

    @property
    def fan_speed(self):
        """Return the fan speed of the vacuum cleaner."""
        if self.vacuum_state is not None:
            speed = self.vacuum_state['suction_grade']
            if speed in FAN_SPEEDS.values():
                return [key for key, value in FAN_SPEEDS.items() if value == speed][0]
            return speed
        return 'Unknown'

    @property
    def fan_speed_list(self):
        """Get the list of available fan speed steps of the vacuum cleaner."""
        return list(sorted(FAN_SPEEDS.keys(), key=lambda s: FAN_SPEEDS[s]))

    @property
    def extra_state_attributes(self):
        """Return the specific state attributes of this vacuum cleaner."""
        attrs = {}
        if self.vacuum_state is not None:
            attrs.update(self.vacuum_state)
            attrs['err_state'] = ERROR_CODES.get(
                int(self.vacuum_state['err_state']), "Unknown error")
            try:
                attrs['status'] = STATE_CODE_TO_STATE[int(self.vacuum_state['run_state'])]
            except KeyError:
                return "Definition missing for state %s" % self.vacuum_state['run_state']
        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def supported_features(self):
        """Flag vacuum cleaner robot features that are supported."""
        return SUPPORT_XIAOMI

    async def _try_command(self, mask_error, func, *args, **kwargs):
        """Call a vacuum command handling error messages."""
        try:
            await self.hass.async_add_executor_job(partial(func, *args, **kwargs))
            return True
        except DeviceException as exc:
            _LOGGER.error(mask_error, exc)
            return False

    async def async_start(self):
        """Start or resume the cleaning task."""
        mode = self.vacuum_state['mode']
        is_mop = self.vacuum_state['is_mop']
        action_mode = 0

        if mode == 4 and self._last_clean_point is not None:
            method = 'set_pointclean'
            param = [1, self._last_clean_point[0], self._last_clean_point[1]]
        else:
            if mode == 2:
                action_mode = 2
            else:
                if is_mop == 2:
                    action_mode = 3
                else:
                    action_mode = is_mop
            if mode == 3:
                method = 'set_mode'
                param = [3, 1]
            else:
                method = 'set_mode_withroom'
                param = [action_mode, 1, 0]
        await self._try_command(
            "Unable to start the vacuum: %s", self._vacuum.raw_command, method, param)

    async def async_pause(self):
        """Pause the cleaning task."""
        mode = self.vacuum_state['mode']
        is_mop = self.vacuum_state['is_mop']
        action_mode = 0

        if mode == 4 and self._last_clean_point is not None:
            method = 'set_pointclean'
            param = [3, self._last_clean_point[0], self._last_clean_point[1]]
        else:
            if mode == 2:
                action_mode = 2
            else:
                if is_mop == 2:
                    action_mode = 3
                else:
                    action_mode = is_mop
            if mode == 3:
                method = 'set_mode'
                param = [3, 3]
            else:
                method = 'set_mode_withroom'
                param = [action_mode, 3, 0]
        await self._try_command("Unable to set pause: %s", self._vacuum.raw_command, method, param)

    async def async_stop(self, **kwargs):
        """Stop the vacuum cleaner."""
        mode = self.vacuum_state['mode']
        if mode == 3:
            method = 'set_mode'
            param = [3, 0]
        elif mode == 4:
            method = 'set_pointclean'
            param = [0, 0, 0]
            self._last_clean_point = None
        else:
            method = 'set_mode'
            param = [0]
        await self._try_command("Unable to stop: %s", self._vacuum.raw_command, method, param)

    async def async_set_fan_speed(self, fan_speed, **kwargs):
        """Set fan speed."""
        if fan_speed.capitalize() in FAN_SPEEDS:
            fan_speed = FAN_SPEEDS[fan_speed.capitalize()]
        else:
            try:
                fan_speed = int(fan_speed)
            except ValueError as exc:
                _LOGGER.error(
                    "Fan speed step not recognized (%s). " "Valid speeds are: %s",
                    exc,
                    self.fan_speed_list,
                )
                return
        await self._try_command(
            "Unable to set fan speed: %s", self._vacuum.raw_command, 'set_suction', [
                fan_speed]
        )

    async def async_return_to_base(self, **kwargs):
        """Set the vacuum cleaner to return to the dock."""
        await self._try_command(
            "Unable to return home: %s", self._vacuum.raw_command, 'set_charge', [1])

    async def async_locate(self, **kwargs):
        """Locate the vacuum cleaner."""
        await self._try_command(
            "Unable to locate the botvac: %s", self._vacuum.raw_command, 'set_resetpos', [1])

    async def async_send_command(self, command, params=None, **kwargs):
        """Send raw command."""
        await self._try_command(
            "Unable to send command to the vacuum: %s",
            self._vacuum.raw_command,
            command,
            params,
        )

    def update(self):
        """Fetch state from the device."""
        try:
            state = self._vacuum.raw_command('get_prop', ALL_PROPS)

            self.vacuum_state = dict(zip(ALL_PROPS, state))

            self._available = True

            # Automatically set mop based on mop_type
            is_mop = bool(self.vacuum_state['is_mop'])
            has_mop = bool(self.vacuum_state['mop_type'])

            update_mop = None
            if is_mop and not has_mop:
                update_mop = 0
            elif not is_mop and has_mop:
                update_mop = 1

            if update_mop is not None:
                self._vacuum.raw_command('set_mop', [update_mop])
                self.update()
        except OSError as exc:
            _LOGGER.error("Got OSError while fetching the state: %s", exc)
        except DeviceException as exc:
            _LOGGER.warning("Got exception while fetching the state: %s", exc)

    async def async_clean_zone(self, zone, repeats=1):
        """Clean selected area for the number of repeats indicated."""
        result = []
        i = 0
        for pos_z in zone:
            pos_x1, pos_y2, pos_x2, pos_y1 = pos_z
            res = '_'.join(str(x) for x in [i, 0, pos_x1, pos_y1, pos_x1, pos_y2,
                                            pos_x2, pos_y2, pos_x2, pos_y1])
            for _ in range(repeats):
                result.append(res)
                i += 1
        result = [i] + result

        await self._try_command(
                "Unable to clean zone: %s", self._vacuum.raw_command, 'set_uploadmap', [1]) \
            and await self._try_command(
                "Unable to clean zone: %s", self._vacuum.raw_command, 'set_zone', result) \
            and await self._try_command(
                "Unable to clean zone: %s", self._vacuum.raw_command, 'set_mode', [3, 1])

    async def async_clean_point(self, point):
        """Clean selected area"""
        pos_x, pos_y = point
        self._last_clean_point = point
        await self._try_command(
            "Unable to clean point: %s", self._vacuum.raw_command, 'set_uploadmap', [0]) \
                and await self._try_command(
                    "Unable to clean point: %s", self._vacuum.raw_command, 'set_pointclean', [
                        1, pos_x, pos_y])

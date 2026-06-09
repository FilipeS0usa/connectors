import time
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch, sentinel

import thehive as module


def _make_config():
    """Build a lightweight stand-in for `ConnectorSettings` exposing the `thehive`
    and `connector` attributes that `TheHive` reads."""
    config = MagicMock()
    thehive = config.thehive
    thehive.url = "https://thehive.test"
    thehive.api_key = "api-key"
    thehive.organization_name = "MyOrg"
    thehive.check_ssl = True
    thehive.import_from_date = None
    thehive.import_only_tlp = ["0", "1", "2", "3", "4"]
    thehive.import_alerts = True
    thehive.import_attachments = False
    thehive.severity_mapping = [
        "1:01 - low",
        "2:02 - medium",
        "3:03 - high",
        "4:04 - critical",
    ]
    thehive.case_status_mapping = []
    thehive.task_status_mapping = []
    thehive.alert_status_mapping = []
    thehive.user_mapping = []
    thehive.case_tag_whitelist = []
    thehive.interval = 5
    # Connector section: by default duration_period is not explicitly set, so the
    # connector falls back to thehive.interval for scheduling.
    config.connector.duration_period = timedelta(minutes=5)
    config.connector.model_fields_set = set()
    return config


@patch.object(module, "TheHiveApi")
class TheHiveTest(unittest.TestCase):

    def _make_connector(self):
        """Instantiate the connector with a mocked config and helper. `TheHiveApi`
        is patched at the class level, so `connector.thehive_api` is its return value.
        """
        return module.TheHive(config=_make_config(), helper=MagicMock())

    def test_init_wires_config(self, m_thehiveapi):
        """The constructor must read its settings from the config object."""
        _connector = self._make_connector()

        self.assertEqual(_connector.thehive_url, "https://thehive.test")
        self.assertEqual(_connector.thehive_api_key, "api-key")
        self.assertEqual(_connector.thehive_import_only_tlp, ["0", "1", "2", "3", "4"])
        self.assertFalse(_connector.thehive_import_attachments)
        self.assertEqual(_connector.thehive_interval, 5)
        # severity_mapping string pairs are parsed into a {level: label} dict
        self.assertEqual(_connector.severity_mapping[1], "01 - low")
        self.assertEqual(_connector.severity_mapping[4], "04 - critical")

    def test_run_uses_explicit_duration_period(self, m_thehiveapi):
        """When CONNECTOR_DURATION_PERIOD is explicitly set, it drives scheduling."""
        config = _make_config()
        config.connector.model_fields_set = {"duration_period"}
        config.connector.duration_period = timedelta(minutes=10)
        _connector = module.TheHive(config=config, helper=MagicMock())

        _connector.run()

        _connector.helper.schedule_process.assert_called_once()
        _, kwargs = _connector.helper.schedule_process.call_args
        self.assertEqual(kwargs["duration_period"], 600)
        self.assertEqual(kwargs["message_callback"], _connector.process_message)

    def test_run_falls_back_to_interval(self, m_thehiveapi):
        """Without an explicit duration_period, scheduling uses THEHIVE_INTERVAL (minutes)."""
        config = _make_config()
        config.connector.model_fields_set = set()
        config.thehive.interval = 30
        _connector = module.TheHive(config=config, helper=MagicMock())

        _connector.run()

        _, kwargs = _connector.helper.schedule_process.call_args
        self.assertEqual(kwargs["duration_period"], 1800)

    def test_process_comments_simple(self, m_thehiveapi):
        """testing the calls made to hive API by the process_comments function"""
        _now = int(time.time() * 1000)
        _case = MagicMock()
        _case_values = {
            "_id": sentinel.case_id,
            "title": MagicMock(),
            "_createdAt": _now,
        }
        _case.get.side_effect = _case_values.get

        _stix_case = MagicMock()
        _stix_case.id = sentinel.stix_case_id

        _comment = "this is my comment"
        _case_comment = MagicMock()
        _case_comment_values = {"message": _comment, "_createdAt": _now}
        _case_comment.get.side_effect = _case_comment_values.get
        m_thehiveapi.return_value.case.find_comments.return_value = [_case_comment]

        _connector = self._make_connector()

        processed_comments = _connector.process_comments(_case, _stix_case)

        m_thehiveapi.return_value.case.find_comments.assert_called_with(
            case_id=sentinel.case_id,
            sortby=module.Asc("_createdAt"),
            paginate=module.Paginate(start=0, end=10),
        )
        self.assertEqual(len(processed_comments), 1)
        self.assertEqual(processed_comments[0]["type"], "note")
        self.assertEqual(processed_comments[0]["content"], _comment)
        self.assertEqual(processed_comments[0]["object_refs"], [sentinel.stix_case_id])

    def test_process_comments_duplicate(self, m_thehiveapi):
        """testing process_comments proper handling of duplicates"""
        _now = int(time.time() * 1000)
        _case = MagicMock()
        _case_values = {
            "_id": sentinel.case_id,
            "title": MagicMock(),
            "_createdAt": _now,
        }
        _case.get.side_effect = _case_values.get

        _stix_case = MagicMock()
        _stix_case.id = sentinel.stix_case_id

        _comment = "this is my comment"
        _case_comment = MagicMock()
        _case_comment_values = {"message": _comment, "_createdAt": _now}
        _case_comment.get.side_effect = _case_comment_values.get
        m_thehiveapi.return_value.case.find_comments.return_value = [
            _case_comment,
            _case_comment,
        ]

        _connector = self._make_connector()

        processed_comments = _connector.process_comments(_case, _stix_case)

        m_thehiveapi.return_value.case.find_comments.assert_called_with(
            case_id=sentinel.case_id,
            sortby=module.Asc("_createdAt"),
            paginate=module.Paginate(start=0, end=10),
        )
        self.assertEqual(len(processed_comments), 2)
        self.assertEqual(processed_comments[0]["type"], "note")
        self.assertEqual(processed_comments[0]["type"], processed_comments[1]["type"])
        self.assertEqual(processed_comments[0]["content"], _comment)
        self.assertEqual(
            processed_comments[0]["content"], processed_comments[1]["content"]
        )
        self.assertEqual(processed_comments[0]["object_refs"], [sentinel.stix_case_id])
        self.assertEqual(
            processed_comments[0]["object_refs"], processed_comments[1]["object_refs"]
        )

        self.assertEqual(processed_comments[0]["id"], processed_comments[1]["id"])

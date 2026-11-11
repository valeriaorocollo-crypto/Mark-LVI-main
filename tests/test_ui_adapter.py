from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import ui_adapter


class UiAdapterTests(unittest.TestCase):
    def test_non_windows_adapter_is_unavailable_and_read_only(self) -> None:
        with patch.object(ui_adapter.platform, "system", return_value="Linux"):
            result = ui_adapter.capabilities()

        self.assertFalse(result.available)
        self.assertTrue(result.read_only)
        self.assertEqual(result.capabilities, ())

    def test_missing_pywinauto_is_reported_without_installing(self) -> None:
        with (
            patch.object(ui_adapter.platform, "system", return_value="Windows"),
            patch.object(ui_adapter, "capabilities") as capability,
        ):
            capability.return_value = ui_adapter.ApplicationCapabilities(
                "Windows", False, True, (), "pywinauto is not installed."
            )
            with self.assertRaisesRegex(RuntimeError, "pywinauto"):
                ui_adapter.inspect_windows()

    def test_windows_capabilities_mark_focus_as_non_read_only(self) -> None:
        fake_pywinauto = object()
        with (
            patch.object(ui_adapter.platform, "system", return_value="Windows"),
            patch.dict("sys.modules", {"pywinauto": fake_pywinauto}),
        ):
            result = ui_adapter.capabilities()

        self.assertFalse(result.read_only)
        self.assertIn("focus_verified_control", result.capabilities)

    def test_broken_uia_backend_is_reported_as_unavailable(self) -> None:
        with (
            patch.object(ui_adapter.platform, "system", return_value="Windows"),
            patch.dict("sys.modules", {"pywinauto": None}),
        ):
            result = ui_adapter.capabilities()

        self.assertFalse(result.available)
        self.assertIn("unavailable", result.reason)

    def test_window_limit_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            ui_adapter.inspect_windows(51)
        with self.assertRaises(ValueError):
            ui_adapter.inspect_windows(True)

    def test_password_control_text_is_hidden(self) -> None:
        class Info:
            control_type = "Edit"
            name = "Account"

        class PasswordElement:
            CurrentIsPassword = True

        class PasswordInfo:
            control_type = "Edit"
            name = "Account"
            element = PasswordElement()

        class PasswordInfo:
            control_type = "Password"

        class Control:
            element_info = Info()

            def window_text(self) -> str:
                return "visible text"

        class PasswordControl(Control):
            element_info = type("Info", (), {"control_type": "Password"})()

        class UiaPasswordControl(Control):
            element_info = PasswordInfo()

        self.assertEqual(ui_adapter._safe_text(Control()), "visible text")
        self.assertEqual(ui_adapter._safe_text(PasswordControl()), "")
        self.assertEqual(ui_adapter._safe_text(UiaPasswordControl()), "")

    def test_uia_password_property_blocks_read_and_write(self) -> None:
        class Control:
            element_info = SimpleNamespace(
                control_type="Edit",
                name="Account",
                automation_id="account",
                element=SimpleNamespace(CurrentIsPassword=True),
            )
            written = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_edit_text(self, _value):
                self.written = True

            def get_value(self):
                return "must-not-be-read"

        control = Control()
        window = SimpleNamespace(descendants=lambda: [control])
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Account",
            "control_type": "Edit",
            "automation_id": "account",
        }
        with (
            patch.object(
                ui_adapter,
                "capabilities",
                return_value=ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("read_allowed_text",)
                ),
            ),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            read_result = ui_adapter.read_control(selector)
            write_result = ui_adapter.write_control(selector, "new-value")

        self.assertEqual(read_result["status"], "failed")
        self.assertEqual(read_result["text"], "")
        self.assertNotIn("must-not-be-read", str(read_result))
        self.assertEqual(write_result["status"], "failed")
        self.assertFalse(control.written)

    def test_inspection_backend_error_is_not_an_empty_success(self) -> None:
        fake_module = SimpleNamespace(
            Desktop=lambda **_kwargs: (_ for _ in ()).throw(OSError("secret detail"))
        )
        with (
            patch.object(
                ui_adapter,
                "capabilities",
                return_value=ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("list_windows",)
                ),
            ),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            with self.assertRaisesRegex(RuntimeError, "OSError") as raised:
                ui_adapter.inspect_windows()
        self.assertNotIn("secret detail", str(raised.exception))

    def test_control_state_read_error_is_explicit_and_not_assumed_false(self):
        class Control:
            element_info = SimpleNamespace(
                control_type="Button", name="Save", automation_id="save"
            )

            def is_enabled(self):
                raise RuntimeError("private backend detail")

            def is_visible(self):
                return True

            def window_text(self):
                return "Save"

        record = ui_adapter._control_record(Control())

        self.assertIsNone(record["enabled"])
        self.assertEqual(record["inspection_errors"], {"enabled": "RuntimeError"})
        found = ui_adapter.find_controls(
            [{"name": "Demo", "controls": [record]}],
            name="Save",
            enabled=True,
        )
        self.assertEqual(found["status"], "unverified")
        self.assertIn("unreadable state", found["reason"])

    def test_find_controls_returns_selector_for_one_exact_match(self) -> None:
        result = ui_adapter.find_controls(
            [{"name": "Demo", "controls": [{
                "name": "Save", "control_type": "Button",
                "automation_id": "save", "enabled": True, "visible": True,
            }]}],
            name="save",
            control_type="button",
            enabled=True,
        )

        self.assertEqual(result["status"], "found")
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["matches"][0]["selector"]["automation_id"], "save")

    def test_find_controls_rejects_ambiguous_matches(self) -> None:
        windows = [{
            "name": "Demo",
            "controls": [
                {"name": "Open", "control_type": "Button",
                 "enabled": True, "visible": True},
                {"name": "Open", "control_type": "Button",
                 "enabled": True, "visible": True},
            ],
        }]

        result = ui_adapter.find_controls(windows, name="Open")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["recovery"], "target_ambiguous")
        self.assertTrue(result["ambiguous"])

    def test_find_controls_requires_a_selector(self) -> None:
        with self.assertRaises(ValueError):
            ui_adapter.find_controls([])

    def test_focus_control_rejects_password_selector(self) -> None:
        result = ui_adapter.focus_control({
            "window_name": "Demo",
            "name": "Password",
            "control_type": "Password",
            "automation_id": "",
        })

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["verified"])

    def test_focus_control_requires_structured_selector(self) -> None:
        with self.assertRaises(ValueError):
            ui_adapter.focus_control({"window_name": "Demo"})

    def test_focus_control_rejects_oversized_selector_fields(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "",
        }
        for field, value in (
            ("window_name", "x" * 301),
            ("name", "x" * 301),
            ("control_type", "x" * 101),
            ("automation_id", "x" * 201),
        ):
            with self.subTest(field=field):
                oversized = dict(selector)
                oversized[field] = value
                with self.assertRaises(ValueError):
                    ui_adapter.focus_control(oversized)

    def test_focus_control_uses_unique_control_and_verifies_focus(self) -> None:
        class Info:
            control_type = "Button"
            name = "Save"
            automation_id = "save"

        class Control:
            element_info = Info()
            focused = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_focus(self):
                self.focused = True

            def has_focus(self):
                return self.focused

        control = Control()
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(
            windows=lambda **_kwargs: [window],
        )
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["verified"])
        self.assertTrue(control.focused)

    def test_focus_control_rejects_ambiguous_controls_without_focusing(self) -> None:
        class Info:
            control_type = "Button"
            name = "Save"
            automation_id = ""

        class Control:
            element_info = Info()
            focused = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_focus(self):
                self.focused = True

            def has_focus(self):
                return self.focused

        controls = [Control(), Control()]
        window = SimpleNamespace(descendants=lambda: controls)
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "ambiguous")
        self.assertFalse(any(control.focused for control in controls))

    def test_focus_control_bounds_descendant_scan(self) -> None:
        class Info:
            control_type = "Button"
            name = "Save"
            automation_id = "save"

        class Control:
            def __init__(self, name):
                self.element_info = SimpleNamespace(
                    control_type="Button",
                    name=name,
                    automation_id="save",
                )
                self.focused = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_focus(self):
                self.focused = True

            def has_focus(self):
                return self.focused

        controls = [Control("Save") for _ in range(100)]
        controls.append(Control("Target"))
        window = SimpleNamespace(descendants=lambda: controls)
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Target",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "not_found")
        self.assertFalse(controls[-1].focused)

    def test_focus_control_reports_unverified_focus(self) -> None:
        class Info:
            control_type = "Button"
            name = "Save"
            automation_id = "save"

        class Control:
            element_info = Info()
            focused = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_focus(self):
                pass

            def has_focus(self):
                return False

        window = SimpleNamespace(descendants=lambda: [Control()])
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["recovery"], "focus_lost")
        self.assertFalse(result["verified"])

    def test_focus_control_fails_if_control_disappears_during_focus(self) -> None:
        control = SimpleNamespace(
            element_info=SimpleNamespace(
                control_type="Button",
                name="Save",
                automation_id="save",
            ),
            is_visible=lambda: True,
            is_enabled=lambda: True,
            set_focus=lambda: (_ for _ in ()).throw(
                RuntimeError("control disappeared")
            ),
        )
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["verified"])
        self.assertIn("RuntimeError", result["reason"])

    def test_focus_control_reads_native_uia_focus_when_wrapper_lacks_method(self) -> None:
        class Element:
            CurrentHasKeyboardFocus = True

        control = SimpleNamespace(
            element_info=SimpleNamespace(
                control_type="Button",
                name="Save",
                automation_id="save",
                element=Element(),
            ),
            is_visible=lambda: True,
            is_enabled=lambda: True,
            set_focus=lambda: None,
        )
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["verified"])

    def test_focus_control_reports_unverified_native_focus(self) -> None:
        class Element:
            CurrentHasKeyboardFocus = False

        control = SimpleNamespace(
            element_info=SimpleNamespace(
                control_type="Button",
                name="Save",
                automation_id="save",
                element=Element(),
            ),
            is_visible=lambda: True,
            is_enabled=lambda: True,
            set_focus=lambda: None,
        )
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["verified"])

    def test_focus_control_fails_without_focus_evidence(self) -> None:
        control = SimpleNamespace(
            element_info=SimpleNamespace(
                control_type="Button",
                name="Save",
                automation_id="save",
                element=SimpleNamespace(),
            ),
            is_visible=lambda: True,
            is_enabled=lambda: True,
            set_focus=lambda: None,
        )
        window = SimpleNamespace(descendants=lambda: [control])
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Save",
            "control_type": "Button",
            "automation_id": "save",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("focus_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.focus_control(selector)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["verified"])

    def test_activate_window_requires_one_visible_window_and_verifies_focus(self) -> None:
        class Window:
            def __init__(self):
                self.focused = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_focus(self):
                self.focused = True

            def has_focus(self):
                return self.focused

        window = Window()
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        with (
            patch.object(ui_adapter, "platform") as platform,
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("activate_verified_window",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            platform.system.return_value = "Windows"
            result = ui_adapter.activate_window("Demo")

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["verified"])
        self.assertTrue(window.focused)

    def test_activate_window_rejects_ambiguous_windows(self) -> None:
        windows = [SimpleNamespace(), SimpleNamespace()]
        desktop = SimpleNamespace(windows=lambda **_kwargs: windows)
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        with (
            patch.object(ui_adapter, "platform") as platform,
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("activate_verified_window",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            platform.system.return_value = "Windows"
            result = ui_adapter.activate_window("Demo")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["recovery"], "target_ambiguous")
        self.assertFalse(result["verified"])

    def test_write_control_sets_and_verifies_one_edit(self) -> None:
        class Control:
            element_info = SimpleNamespace(
                control_type="Edit", name="Name", automation_id="name"
            )
            value = ""

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_edit_text(self, value):
                self.value = value

            def window_text(self):
                return self.value

        control = Control()
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Name",
            "control_type": "Edit",
            "automation_id": "name",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("write_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            text = "synthetic-" * 70
            result = ui_adapter.write_control(selector, text)

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["verified"])
        self.assertEqual(control.value, text)

    def test_write_control_exception_after_setter_is_unverified(self) -> None:
        class Control:
            element_info = SimpleNamespace(
                control_type="Edit", name="Name", automation_id="name"
            )
            value = ""

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def set_edit_text(self, value):
                self.value = value
                raise RuntimeError("private backend detail")

            def get_value(self):
                return self.value

        control = Control()
        window = SimpleNamespace(descendants=lambda: [control])
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Name",
            "control_type": "Edit",
            "automation_id": "name",
        }
        with (
            patch.object(
                ui_adapter,
                "capabilities",
                return_value=ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("write_verified_control",)
                ),
            ),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.write_control(selector, "synthetic value")

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["recovery"], "effect_ambiguous")
        self.assertFalse(result["verified"])
        self.assertEqual(control.value, "synthetic value")
        self.assertNotIn("private backend detail", str(result))

    def test_write_control_rejects_password_and_non_edit_controls(self) -> None:
        base = {
            "window_name": "Demo",
            "name": "Name",
            "control_type": "Button",
            "automation_id": "",
        }
        result = ui_adapter.write_control(base, "secret")
        self.assertEqual(result["status"], "failed")
        self.assertIn("only Edit", result["reason"])
        password = dict(base, name="Password", control_type="Edit")
        result = ui_adapter.write_control(password, "secret")
        self.assertEqual(result["status"], "failed")
        self.assertIn("password", result["reason"])

    def test_invoke_control_verifies_an_observable_state_change(self) -> None:
        class Control:
            element_info = SimpleNamespace(
                control_type="Button", name="Next", automation_id="next"
            )
            invoked = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def invoke(self):
                self.invoked = True
                self.element_info.name = "Completed"

            def window_text(self):
                return self.element_info.name

        control = Control()
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("invoke_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.invoke_control(selector)

        self.assertEqual(result["status"], "done")
        self.assertTrue(result["verified"])
        self.assertTrue(control.invoked)

    def test_invoke_control_does_not_verify_success_when_window_disappears(self):
        class Control:
            element_info = SimpleNamespace(
                control_type="Button", name="Next", automation_id="next"
            )
            invoked = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def invoke(self):
                self.invoked = True

            def window_text(self):
                return "Next"

        control = Control()
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        window_queries = 0

        def find_windows(**_kwargs):
            nonlocal window_queries
            window_queries += 1
            return [window] if window_queries == 1 else []

        desktop = SimpleNamespace(windows=find_windows)
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with (
            patch.object(
                ui_adapter,
                "capabilities",
                return_value=ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("invoke_verified_control",)
                ),
            ),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.invoke_control(selector)

        self.assertTrue(control.invoked)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["recovery"], "window_changed")
        self.assertFalse(result["verified"])

    def test_invoke_control_exception_after_invocation_is_unverified(self) -> None:
        class Control:
            element_info = SimpleNamespace(
                control_type="Button", name="Next", automation_id="next"
            )
            invoked = False

            def is_visible(self):
                return True

            def is_enabled(self):
                return True

            def invoke(self):
                self.invoked = True
                raise RuntimeError("private backend detail")

            def window_text(self):
                return "Next"

        control = Control()
        window = SimpleNamespace(descendants=lambda: [control], has_focus=lambda: True)
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with (
            patch.object(
                ui_adapter,
                "capabilities",
                return_value=ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("invoke_verified_control",)
                ),
            ),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.invoke_control(selector)

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["recovery"], "effect_ambiguous")
        self.assertFalse(result["verified"])
        self.assertTrue(control.invoked)
        self.assertNotIn("private backend detail", str(result))

    def test_invoke_control_does_not_claim_success_without_transition(self) -> None:
        control = SimpleNamespace(
            element_info=SimpleNamespace(
                control_type="Button", name="Next", automation_id="next"
            ),
            is_visible=lambda: True,
            is_enabled=lambda: True,
            invoke=lambda: None,
            window_text=lambda: "Next",
        )
        window = SimpleNamespace(
            descendants=lambda: [control], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("invoke_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.invoke_control(selector)

        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["verified"])

    def test_invoke_control_distinguishes_missing_from_ambiguous(self) -> None:
        window = SimpleNamespace(
            descendants=lambda: [], has_focus=lambda: True
        )
        desktop = SimpleNamespace(windows=lambda **_kwargs: [window])
        fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
        selector = {
            "window_name": "Demo",
            "name": "Next",
            "control_type": "Button",
            "automation_id": "next",
        }
        with (
            patch.object(ui_adapter, "capabilities", return_value=
                ui_adapter.ApplicationCapabilities(
                    "Windows", True, False, ("invoke_verified_control",)
                )),
            patch.dict("sys.modules", {"pywinauto": fake_module}),
        ):
            result = ui_adapter.invoke_control(selector)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["recovery"], "control_missing")
        self.assertFalse(result["verified"])

    def test_read_control_classifies_window_and_control_disappearance(self) -> None:
        selector = {
            "window_name": "Demo",
            "name": "Status",
            "control_type": "Text",
            "automation_id": "status",
        }
        cases = (
            ([], "window_changed"),
            ([SimpleNamespace(descendants=lambda: [])], "control_missing"),
        )
        for windows, expected_recovery in cases:
            with self.subTest(expected_recovery=expected_recovery):
                desktop = SimpleNamespace(windows=lambda **_kwargs: windows)
                fake_module = SimpleNamespace(Desktop=lambda **_kwargs: desktop)
                with (
                    patch.object(
                        ui_adapter,
                        "capabilities",
                        return_value=ui_adapter.ApplicationCapabilities(
                            "Windows", True, False, ("read_allowed_text",)
                        ),
                    ),
                    patch.dict("sys.modules", {"pywinauto": fake_module}),
                ):
                    result = ui_adapter.read_control(selector)

                self.assertEqual(result["status"], "not_found")
                self.assertEqual(result["recovery"], expected_recovery)
                self.assertFalse(result["verified"])

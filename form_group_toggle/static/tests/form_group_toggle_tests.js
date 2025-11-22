/** @odoo-module **/

import { InnerGroup, OuterGroup } from "@web/views/form/form_group/form_group";
import { getFixture, mount, patchWithCleanup } from "@web/../tests/helpers/utils";
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { makeView, setupViewRegistries } from "@web/../tests/views/helpers";

const { test, module } = QUnit;

module("Form Group Toggle", (hooks) => {
    hooks.beforeEach(() => {
        setupViewRegistries();
    });

    module("Component Patching");

    test("InnerGroup has initializeToggle method", async function (assert) {
        assert.ok(
            typeof InnerGroup.prototype.initializeToggle === "function",
            "InnerGroup should have initializeToggle method"
        );
    });

    test("OuterGroup has initializeToggle method", async function (assert) {
        assert.ok(
            typeof OuterGroup.prototype.initializeToggle === "function",
            "OuterGroup should have initializeToggle method"
        );
    });

    test("InnerGroup has toggleGroup method", async function (assert) {
        assert.ok(
            typeof InnerGroup.prototype.toggleGroup === "function",
            "InnerGroup should have toggleGroup method"
        );
    });

    test("OuterGroup has toggleGroup method", async function (assert) {
        assert.ok(
            typeof OuterGroup.prototype.toggleGroup === "function",
            "OuterGroup should have toggleGroup method"
        );
    });

    module("Toggle Functionality");

    test("toggle icon appears for groups with title", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            display_name: { string: "Name", type: "char" },
                            email: { string: "Email", type: "char" },
                            phone: { string: "Phone", type: "char" },
                        },
                        records: [
                            {
                                id: 1,
                                display_name: "Test Partner",
                                email: "test@example.com",
                                phone: "123456",
                            },
                        ],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group>
                            <group string="Contact Information">
                                <field name="email"/>
                                <field name="phone"/>
                            </group>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const toggleIcon = target.querySelector(".o_group_toggle_icon");
        assert.ok(toggleIcon, "Toggle icon should be present for group with title");
        assert.ok(
            toggleIcon.classList.contains("fa-chevron-down"),
            "Icon should show chevron-down by default"
        );
    });

    test("toggle header is clickable", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            display_name: { string: "Name", type: "char" },
                            email: { string: "Email", type: "char" },
                        },
                        records: [{ id: 1, display_name: "Test", email: "test@example.com" }],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group string="Test Group">
                            <field name="email"/>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const toggleHeader = target.querySelector(".o_group_toggle_header");
        assert.ok(toggleHeader, "Toggle header should be present");

        const computedStyle = window.getComputedStyle(toggleHeader);
        assert.ok(
            computedStyle.cursor === "pointer" || toggleHeader.style.cursor === "pointer",
            "Toggle header should have pointer cursor"
        );
    });

    test("clicking header toggles content visibility", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            email: { string: "Email", type: "char" },
                            phone: { string: "Phone", type: "char" },
                        },
                        records: [{ id: 1, email: "test@example.com", phone: "123" }],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group string="Contact Info">
                            <field name="email"/>
                            <field name="phone"/>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const toggleHeader = target.querySelector(".o_group_toggle_header");
        const toggleContent = target.querySelector(".o_group_toggle_content");
        const toggleIcon = target.querySelector(".o_group_toggle_icon");

        assert.ok(toggleHeader, "Toggle header should exist");
        assert.ok(toggleContent, "Toggle content should exist");
        assert.ok(toggleIcon, "Toggle icon should exist");

        // Initial state - expanded
        assert.notEqual(
            toggleContent.style.display,
            "none",
            "Content should be visible initially"
        );
        assert.ok(
            toggleIcon.classList.contains("fa-chevron-down"),
            "Icon should be chevron-down when expanded"
        );

        // Click to collapse
        toggleHeader.click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(
            toggleContent.style.display,
            "none",
            "Content should be hidden after click"
        );
        assert.ok(
            toggleIcon.classList.contains("fa-chevron-right"),
            "Icon should be chevron-right when collapsed"
        );
        assert.notOk(
            toggleIcon.classList.contains("fa-chevron-down"),
            "Icon should not have chevron-down when collapsed"
        );

        // Click to expand
        toggleHeader.click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(
            toggleContent.style.display,
            "contents",
            "Content should be visible again after second click"
        );
        assert.ok(
            toggleIcon.classList.contains("fa-chevron-down"),
            "Icon should be chevron-down when expanded again"
        );
        assert.notOk(
            toggleIcon.classList.contains("fa-chevron-right"),
            "Icon should not have chevron-right when expanded"
        );
    });

    test("multiple groups toggle independently", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            email: { string: "Email", type: "char" },
                            phone: { string: "Phone", type: "char" },
                            street: { string: "Street", type: "char" },
                            city: { string: "City", type: "char" },
                        },
                        records: [
                            {
                                id: 1,
                                email: "test@example.com",
                                phone: "123",
                                street: "Main St",
                                city: "City",
                            },
                        ],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group>
                            <group string="Contact Information">
                                <field name="email"/>
                                <field name="phone"/>
                            </group>
                            <group string="Address">
                                <field name="street"/>
                                <field name="city"/>
                            </group>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const toggleHeaders = target.querySelectorAll(".o_group_toggle_header");
        const toggleContents = target.querySelectorAll(".o_group_toggle_content");

        assert.equal(toggleHeaders.length, 2, "Should have 2 toggle headers");
        assert.equal(toggleContents.length, 2, "Should have 2 toggle contents");

        // Collapse first group
        toggleHeaders[0].click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(
            toggleContents[0].style.display,
            "none",
            "First group should be collapsed"
        );
        assert.notEqual(
            toggleContents[1].style.display,
            "none",
            "Second group should still be expanded"
        );

        // Collapse second group
        toggleHeaders[1].click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(
            toggleContents[0].style.display,
            "none",
            "First group should still be collapsed"
        );
        assert.equal(
            toggleContents[1].style.display,
            "none",
            "Second group should now be collapsed"
        );

        // Expand first group
        toggleHeaders[0].click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(
            toggleContents[0].style.display,
            "contents",
            "First group should be expanded"
        );
        assert.equal(
            toggleContents[1].style.display,
            "none",
            "Second group should still be collapsed"
        );
    });

    module("Edge Cases");

    test("groups without string attribute don't get toggle", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            email: { string: "Email", type: "char" },
                            phone: { string: "Phone", type: "char" },
                        },
                        records: [{ id: 1, email: "test@example.com", phone: "123" }],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group>
                            <field name="email"/>
                            <field name="phone"/>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        // Group without string should not have toggle elements
        const toggleIcons = target.querySelectorAll(".o_group_toggle_icon");
        assert.equal(
            toggleIcons.length,
            0,
            "Group without title should not have toggle icon"
        );
    });

    test("toggleGroup method handles display states correctly", async function (assert) {
        const target = getFixture();

        await makeView({
            type: "form",
            resModel: "partner",
            serverData: {
                models: {
                    partner: {
                        fields: {
                            email: { string: "Email", type: "char" },
                        },
                        records: [{ id: 1, email: "test@example.com" }],
                    },
                },
            },
            arch: `
                <form>
                    <sheet>
                        <group string="Test Group">
                            <field name="email"/>
                        </group>
                    </sheet>
                </form>
            `,
            resId: 1,
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const toggleIcon = target.querySelector(".o_group_toggle_icon");
        const toggleContent = target.querySelector(".o_group_toggle_content");

        // Test collapsing
        assert.ok(toggleIcon.classList.contains("fa-chevron-down"), "Initially expanded");

        toggleIcon.click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(toggleContent.style.display, "none", "Content hidden");
        assert.ok(toggleIcon.classList.contains("fa-chevron-right"), "Icon points right");

        // Test expanding
        toggleIcon.click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        assert.equal(toggleContent.style.display, "contents", "Content visible");
        assert.ok(toggleIcon.classList.contains("fa-chevron-down"), "Icon points down");
    });
});

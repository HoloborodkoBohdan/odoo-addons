/** @odoo-module **/

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { InnerGroup, OuterGroup } from "@web/views/form/form_group/form_group";

function patchGroupComponent(GroupComponent) {
    patch(GroupComponent.prototype, {
        setup() {
            super.setup(...arguments);
            onMounted(() => {
                this.initializeToggle();
            });
        },

        initializeToggle() {
            if (!this.__owl__ || !this.__owl__.bdom || !this.__owl__.bdom.el) {
                return;
            }

            const groupEl = this.__owl__.bdom.el;

            if (!this.props.slots?.title && !this.props.string) {
                return;
            }

            const toggleHeader = groupEl.querySelector('.o_group_toggle_header');
            const toggleIcon = groupEl.querySelector('.o_group_toggle_icon');
            const toggleContent = groupEl.querySelector('.o_group_toggle_content');

            if (!toggleHeader || !toggleIcon || !toggleContent) {
                return;
            }

            const groupName = this.props.name || '';
            const isInitiallyCollapsed = groupEl.closest('[data-group-collapsed]')?.dataset.groupCollapsed === groupName;

            if (isInitiallyCollapsed) {
                toggleContent.style.display = 'none';
                toggleIcon.classList.remove('fa-chevron-down');
                toggleIcon.classList.add('fa-chevron-right');
            }

            toggleHeader.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleGroup(toggleIcon, toggleContent);
            });
        },

        toggleGroup(icon, content) {
            if (content.style.display === 'none') {
                // Expand
                content.style.display = 'contents';
                icon.classList.remove('fa-chevron-right');
                icon.classList.add('fa-chevron-down');
            } else {
                // Collapse
                content.style.display = 'none';
                icon.classList.remove('fa-chevron-down');
                icon.classList.add('fa-chevron-right');
            }
        },
    });
}

patchGroupComponent(InnerGroup);
patchGroupComponent(OuterGroup);

To use this module:

1. Install the module
2. Open any form view with groups that have labels
3. Click on the group title or chevron icon to toggle

Any group with a ``string`` attribute will automatically have collapse/expand functionality.

Screenshots
-----------

Groups in opened state:

.. image:: ../static/description/opened.png
   :alt: Groups opened
   :width: 600px

Groups in closed state:

.. image:: ../static/description/closed.png
   :alt: Groups closed
   :width: 600px

Example
-------

.. code-block:: xml

    <group string="Contact Information">
        <field name="email"/>
        <field name="phone"/>
    </group>

The "Contact Information" group will display a chevron icon next to the title.
Click anywhere on the title area to collapse or expand the group content.

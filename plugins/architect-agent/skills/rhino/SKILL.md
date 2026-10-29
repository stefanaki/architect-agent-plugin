---
name: rhino
description: Inspect, model, edit, verify or export architecture geometry in an open Rhino 8 model through the plugin's Rhino MCP tools. Use for any request about the engineer's Rhino model, such as plans, elevations, sections, massing, layers or exports.
---

# Rhino

Talk to the engineer in Greek. Work in the engineer's open project folder: save notes and exports
there, and never in the plugin.

## Connection

The Rhino MCP tools talk to Rhino on `127.0.0.1:1999`. The bundled Rhino package
(`assets/rhinomcp-autostart-*.yak`) starts that listener when Rhino starts.

- **No Rhino tools at all:** the plugin is not enabled, or the app needs a restart. Use the setup skill.
- **A no-connection error:** Rhino is closed, or it needs a restart after the package was
  installed. Ask the engineer to start or restart Rhino. Do not debug the app.
- **The package is not installed yet:** run step 3 of the setup skill.

Do not say Rhino is connected until a harmless read, such as the document info, has succeeded.

## Before changing anything

Read the brief, or ask for one: what to build, the dimensions, and where it goes. Then inspect the
open document:

- units and tolerance
- layers
- the objects the change touches

Ask when the brief and the model disagree. Do not guess. Use `get_modeling_guidance` for
transforms, planar regions and recovery from failed operations. Prefer the dedicated tools over
running code. Use code only when no tool fits, and say that you did.

## While changing

Work in small steps. After each meaningful operation, check the result against the brief:

- dimensions and areas
- placement and alignment
- object counts and layers

A tool that returns without an error has not proven that the result is right. Measure it.

## Report

Tell the engineer:

- what changed;
- the ids of the objects that changed;
- what you measured, and against which value of the brief;
- the paths of any exports in the project folder;
- anything you could not do.

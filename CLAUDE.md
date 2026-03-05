# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Urika is a multi-agent scientific analysis and modelling platform for behavioral and health sciences. Users define an investigation (dataset, question, success criteria) and Urika's agents collaborate to explore data, test competing approaches, and converge on optimized solutions.

## Core Agent Architecture

- **Task Builder Agent**: Scopes investigations with users, spawns Task Agents
- **Task Agent**: Executes analytical work using a growing library of tools
- **Evaluation Agent**: Critiques runs, searches literature, suggests unexplored directions
- **Tool Builder Agent**: Constructs or extends analytical capabilities on demand

## Target Domains

Statistical modelling, machine learning, time series, neuroscience, cognitive neuroscience, linguistics, psychology, motor control, and behavioral data.

## Project Status

Early stage — architecture and tooling decisions are not yet made. See `inital-description.md` for the founding vision.

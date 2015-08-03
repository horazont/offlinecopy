Filter rules
############

The complexity of this project is to create proper filter rules when syncing
back. First of all, for each checked out target which is not contained in
another checked out target, we have a custom filter rule set. That makes things
easier and allows to check out targets from different sources.

Now we have the following scenarios.

Evicting a sub-directory
========================

Let A be the subdirectory to evict. We then have to generate the following
rules:

    - A

This is simple.

A -- Evict

Checking out a directory inside an evicted subdirectory
=======================================================

Let A be an evicted subdirectory. Let B, C and D be path components of the
subdirectory of A which is to be checked out.

    + A/B/C/D/
    - A/B/C/*
    + A/B/C/
    - A/B/*
    + A/B/
    - A/*

A -- Include only subtrees
\_ B -- Include only subtrees (produces - A/B/* as last rule)
   \_ C -- Include only subtrees (produces - A/B/C/* as last rule)
      \_ D -- Include

Checking out another directory inside an evicted subdirectory which already contains a checked-out subdirectory
===============================================================================================================

Let A be an evicted subdirectory. Let B, C and D be path components of the
subdirectory of A which is already checked out and B, C and E the path
components of the new subdirectory to check out.

    + A/B/C/D/
    + A/B/C/E/
    - A/B/C/*
    + A/B/C/
    - A/B/*
    + A/B/
    - A/*

A -- Include only subtrees
\_ B -- Include only subtrees (produces - A/B/* as last rule)
   \_ C -- Include only subtrees (produces - A/B/C/* as last rule)
      \_ E -- Include
      \_ D -- Include

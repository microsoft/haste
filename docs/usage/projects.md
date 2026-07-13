<!-- SOURCE OF TRUTH: This page duplicates the in-app Help Docs
     (ui/src/Components/HelpDocs/HelpDocsProjects.jsx). Keep the two in sync
     until the content is consolidated to a single source. -->

# Projects

## What is a Project?

A project is a way to organize image layers and the damage assessments conducted on
them. It is a collection of imagery files, labels, training checkpoints, and inference
results in various formats.

For example, you can create a new project per disaster event.

## Create a new Project

Project creation requires the following information:

1. **Name** – any suitable name for the project.
2. **Description** – any additional information about the project.
3. **Event Date** – the date that the disaster occurred. This date is stored for
   informational purposes and does not affect any processing.
4. **Affected Countries** – from the dropdown, select the country (or multiple
   countries) that were affected by the disaster. This data is stored for informational
   purposes and does not affect any downstream processing.
5. **Primary Classes** – these are the classes of labels that you will add to an image
   layer to help train the model.

The classes of labels that the model needs to be trained on are:

- Background
- Buildings
- Damaged Building

These classes are provided by default on the project creation form. You can keep the
default colors or change them to suit your needs.

<video controls width="100%" src="../_static/usage/projects/projects-create-a-new-project.mp4">
Your browser does not support the video tag.
</video>

## Edit a Project

You can update the name and description for a project after it was created from the
Projects page.

<video controls width="100%" src="../_static/usage/projects/projects-edit-a-project.mp4">
Your browser does not support the video tag.
</video>

## Delete a Project

You can delete a project using the ellipsis menu on the Projects page. Deleting a
project will delete all associated artifacts such as image layers, labels, and training
results.

<video controls width="100%" src="../_static/usage/projects/projects-delete-a-project.mp4">
Your browser does not support the video tag.
</video>

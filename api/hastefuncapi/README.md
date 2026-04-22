# HASTE Service Functions

## Install Azure Functions Core Tools

Docs: https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local?tabs=windows%2Cisolated-process%2Cnode-v4%2Cpython-v2%2Chttp-trigger%2Ccontainer-apps&pivots=programming-language-javascript

```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

## Create a new function app
```bash
func init hastefuncapi --python
cd hastefuncapi

func new --name GetDashboardData --template "HTTP trigger" # get all dashboard data
func new --name GetProjects --template "HTTP trigger" # get the list of projects
func new --name PutProject --template "HTTP trigger" # create or update a project
func new --name DeleteProject --template "HTTP trigger" #delete a Project
func new --name GetProjectDetails --template "HTTP trigger" #returns project details and layer details (model counts, label counts etc/)
func new --name GetLayerLabelingToolData --template "HTTP trigger" #returns layer labeling tool data
func new --name GetLayerModelsDetails --template "HTTP trigger" #returns layer model details (model status, model list associated to the given layer, etc.)
func new --name GetDefaultModelConfig --template "HTTP trigger" # get default model config
func new --name PutLayer --template "HTTP trigger" #create or update a layer
func new --name GetLayerDetailView --template "HTTP trigger" #returns image layer details. For when you click on an image layer name and go into the detail view
func new --name PutRunModelQueueMessage --template "HTTP trigger" # when you click on the run model button
func new --name PutCancelDeleteModelQueueMessage --template "HTTP trigger" # when you click on the cancel model button in the image layer detail view
func new --name PutRunInferenceQueueMessage --template "HTTP trigger" # when you click on the run inference button
func new --name PutCancelInferenceQueueMessage --template "HTTP trigger" # when you click on the cancel inference button in the image layer detail view
func new --name GetModelInferenceResults --template "HTTP trigger" # when you click on the view results button. This is the data for the visualizer tool.
func new --name GetAdminSettings --template "HTTP trigger" # get all admin settings
func new --name PutLabelToolSettings --template "HTTP trigger" # update label tool settings
func new --name PutBaseModelSettings --template "HTTP trigger" # create or update base model
func new --name DeleteBaseModelSettings --template "HTTP trigger" # delete base model
func new --name PutSourceTypeSettings --template "HTTP trigger" # create or update source type
func new --name DeleteSourceTypeSettings --template "HTTP trigger" # delete source type
func new --name PutUsers --template "HTTP trigger" # create or update user
func new --name GetUsers --template "HTTP trigger" # get all users
func new --name DeleteUsers --template "HTTP trigger" # delete user
func new --name PutDefaultModelConfig --template "HTTP trigger" # create or update default model config
func new --name PutLabelsFromLabelTool --template "HTTP trigger" # create or update labels for a given image layer for the label tool
func new --name GetLabelToolTutorialData --template "HTTP trigger" # get label tool tutorial data for inline guidance in the label tool


func new --name GetCreateModelRunQueueMessage --template "Azure Queue Storage trigger"
func new --name GetUpdateStatusModelRunQueueMessage --template "Azure Queue Storage trigger"
func new --name GetCancelDeleteModelRunQueueMessage --template "Azure Queue Storage trigger"
func new --name GetProcessImageLayerQueueMessage --template "Azure Queue Storage trigger"
```

## Local debugging
1. Add breakpoints at the desired point in code using
```python
breakpoint()
```

2. Launch Functions locally using the target `Launch Functions`
In the Terminal where the functions are running, you will be dropped into the pdb prompt when execution reaches the breakpoint. You can use all features of pdb here.

Note: Using the visual breakpoint setter will not work because the running azure function is not attached to the VSCode python visual debugger
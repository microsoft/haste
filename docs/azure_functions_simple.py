"""Azure Functions Sphinx extension with AST parsing."""

import os
import ast
import re
from typing import Dict, List
from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective


class AzureFunctionDocstrings:
    """Extract docstrings from Azure Functions source code using AST parsing."""
    
    def __init__(self):
        self.docstrings: Dict[str, Dict[str, str]] = {}
        self.signatures: Dict[str, Dict[str, str]] = {}
        self.routes: Dict[str, Dict[str, str]] = {}  # Store route information
    
    def parse_source_file(self, filepath: str):
        """Parse a Python file and extract Azure Function docstrings."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source)
            module_name = os.path.splitext(os.path.basename(filepath))[0]
            
            if module_name not in self.docstrings:
                self.docstrings[module_name] = {}
                self.signatures[module_name] = {}
                self.routes[module_name] = {}
            
            # Look for async function definitions (Azure Functions are async)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    func_name = node.name
                    docstring = ast.get_docstring(node)
                    
                    if docstring:
                        self.docstrings[module_name][func_name] = docstring
                        
                        # Generate function signature
                        args = []
                        for arg in node.args.args:
                            args.append(arg.arg)
                        signature = f"async def {func_name}({', '.join(args)})"
                        self.signatures[module_name][func_name] = signature
                        
                        # Try to extract route information from decorators
                        route_info = self._extract_route_info(node, source)
                        if route_info:
                            self.routes[module_name][func_name] = route_info
                        
                        print(f"Found function {func_name} with docstring")
        
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
    
    def _extract_route_info(self, node, source):
        """Extract route information from function decorators."""
        try:
            # Look for @app.route() decorators
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and 
                    isinstance(decorator.func, ast.Attribute) and
                    decorator.func.attr == 'route'):
                    
                    if decorator.args:
                        route_path = decorator.args[0]
                        if isinstance(route_path, ast.Constant):
                            return route_path.value
        except:
            pass
        return None


class AzureFunctionDirective(SphinxDirective):
    """Azure Function directive with docstring extraction."""
    
    has_content = False
    required_arguments = 0
    optional_arguments = 0
    option_spec = {
        'module': directives.unchanged,
        'function': directives.unchanged,
    }
    
    def run(self):
        """Generate documentation nodes for Azure Function."""
        module_name = self.options.get('module', '')
        function_name = self.options.get('function', '')
        
        if not module_name or not function_name:
            error_node = nodes.error()
            error_node += nodes.Text("azure-function directive requires both module and function options")
            return [error_node]
        
        # Get the docstring extractor from the app
        extractor = getattr(self.state.document.settings.env.app, '_azure_function_extractor', None)
        
        if not extractor:
            info_node = nodes.paragraph()
            info_node += nodes.Text(f"Azure Function: {module_name}.{function_name} (no extractor)")
            return [info_node]
        
        docstring = extractor.docstrings.get(module_name, {}).get(function_name, '')
        signature = extractor.signatures.get(module_name, {}).get(function_name, f'{function_name}(...)')
        route = extractor.routes.get(module_name, {}).get(function_name, '')
        
        if not docstring:
            info_node = nodes.paragraph()
            info_node += nodes.Text(f"Azure Function: {module_name}.{function_name} (no docstring found)")
            return [info_node]
        
        # Parse the docstring to extract structured information
        parsed_doc = self._parse_docstring(docstring)
        
        # Create a description list (like hasteutils functions)
        desc_list = nodes.definition_list()
        desc_item = nodes.definition_list_item()
        
        # Term: function name with signature (as a proper function, not class)
        term = nodes.term()
        
        # Function name in emphasis (italic)
        func_signature = self._extract_params_from_signature(signature)
        func_text = f'{function_name}({func_signature})'
        
        func_emphasis = nodes.emphasis(text=func_text)
        term += func_emphasis
        
        # Add source link
        source_text = nodes.Text(' ')
        term += source_text
        source_link = nodes.reference(text='[source]', refuri='#')
        source_link['classes'] = ['viewcode-link']
        term += source_link
        
        desc_item += term
        
        # Definition: the function documentation
        definition = nodes.definition()
        
        # Function description
        if parsed_doc['description']:
            for desc_line in parsed_doc['description']:
                if desc_line.strip():
                    desc_para = nodes.paragraph()
                    desc_para += nodes.Text(desc_line)
                    definition += desc_para
        
        # Add route info if available
        if route:
            route_para = nodes.paragraph()
            route_para += nodes.strong(text='Route: ')
            route_para += nodes.literal(text=route)
            definition += route_para
        
        # Parameters field list (like hasteutils style)
        if parsed_doc['parameters']:
            param_field_list = nodes.field_list()
            
            for param_name, param_desc in parsed_doc['parameters'].items():
                field = nodes.field()
                field_name = nodes.field_name(text='Parameters')
                field_body = nodes.field_body()
                
                param_para = nodes.paragraph()
                param_para += nodes.strong(text=f'{param_name}')
                param_para += nodes.Text(f' – {param_desc}')
                field_body += param_para
                
                field += field_name
                field += field_body
                param_field_list += field
            
            definition += param_field_list
        
        # Returns field list
        if parsed_doc['returns']:
            ret_field_list = nodes.field_list()
            field = nodes.field()
            field_name = nodes.field_name(text='Returns')
            field_body = nodes.field_body()
            
            ret_para = nodes.paragraph()
            ret_para += nodes.Text(parsed_doc['returns'])
            field_body += ret_para
            
            field += field_name
            field += field_body
            ret_field_list += field
            definition += ret_field_list
        
        desc_item += definition
        desc_list += desc_item
        
        return [desc_list]
    
    def _extract_params_from_signature(self, signature):
        """Extract parameter names from function signature for title."""
        try:
            # Extract just the parameter names, not types
            if '(' in signature and ')' in signature:
                params_part = signature[signature.find('(')+1:signature.rfind(')')]
                if params_part.strip():
                    # Split by comma and clean up
                    params = [p.split(':')[0].strip() for p in params_part.split(',')]
                    return ', '.join(params)
            return ''
        except:
            return ''
    
    def _parse_docstring(self, docstring):
        """Parse docstring to extract structured information."""
        lines = docstring.split('\n')
        
        result = {
            'description': [],
            'parameters': {},
            'returns': '',
            'raises': {}
        }
        
        current_section = 'description'
        current_param = None
        
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
            
            # Check for sections
            if line.lower().startswith('args:') or line.lower().startswith('parameters:'):
                current_section = 'parameters'
                continue
            elif line.lower().startswith('returns:'):
                current_section = 'returns'
                continue
            elif line.lower().startswith('raises:'):
                current_section = 'raises'
                continue
            
            # Parse content based on current section
            if current_section == 'description':
                result['description'].append(line)
            elif current_section == 'parameters':
                # Look for parameter patterns like "param_name: description"
                param_match = re.match(r'(\w+):\s*(.*)', line)
                if param_match:
                    param_name, param_desc = param_match.groups()
                    result['parameters'][param_name] = param_desc
                    current_param = param_name
                elif current_param and line.startswith(' '):
                    # Continuation of parameter description
                    result['parameters'][current_param] += ' ' + line.strip()
            elif current_section == 'returns':
                result['returns'] += line + ' '
        
        # Clean up
        result['returns'] = result['returns'].strip()
        
        return result


class AzureFunctionModuleDirective(SphinxDirective):
    """Directive to auto-generate documentation for all functions in a module."""
    
    has_content = False
    required_arguments = 1  # module name
    optional_arguments = 0
    option_spec = {
        'members': directives.flag,
        'undoc-members': directives.flag,
        'show-inheritance': directives.flag,
    }
    
    def run(self):
        """Generate documentation for all functions in the specified module."""
        module_name = self.arguments[0]
        
        # Get the docstring extractor from the app
        extractor = getattr(self.state.document.settings.env.app, '_azure_function_extractor', None)
        
        if not extractor:
            error_node = nodes.error()
            error_node += nodes.Text("Azure Functions docstring extractor not initialized")
            return [error_node]
        
        if module_name not in extractor.docstrings:
            error_node = nodes.error()
            error_node += nodes.Text(f"Module {module_name} not found")
            return [error_node]
        
        container = nodes.container()
        functions = extractor.docstrings[module_name]
        
        # Check options to decide what to include (matching automodule behavior)
        include_members = 'members' in self.options
        include_undoc = 'undoc-members' in self.options
        
        # If no specific options, default to showing all (like automodule)
        if not include_members and not include_undoc:
            include_members = True
            include_undoc = True
        
        for func_name in sorted(functions.keys()):
            docstring = functions[func_name]
            
            # Skip undocumented functions if undoc-members not specified
            if not docstring.strip() and not include_undoc:
                continue
                
            # Skip documented functions if only undoc-members specified
            if docstring.strip() and include_undoc and not include_members:
                continue
            
            # Create individual function documentation using the single function directive
            func_options = {'module': module_name, 'function': func_name}
            
            func_directive = AzureFunctionDirective(
                'azure-function',
                [],
                func_options,
                content=[],
                lineno=self.lineno,
                content_offset=self.content_offset,
                block_text='',
                state=self.state,
                state_machine=self.state_machine
            )
            
            func_nodes = func_directive.run()
            for node in func_nodes:
                container += node
        
        return [container]


def setup_azure_functions_extractor(app):
    """Initialize the Azure Functions docstring extractor."""
    print("Setting up Azure Functions extractor...")
    extractor = AzureFunctionDocstrings()
    
    # Parse Azure Functions source files
    api_dir = os.path.join(app.srcdir, '..', 'api')
    
    # Parse hastefuncapi
    hastefuncapi_path = os.path.join(api_dir, 'hastefuncapi', 'function_app.py')
    if os.path.exists(hastefuncapi_path):
        extractor.parse_source_file(hastefuncapi_path)
        print(f"Parsed Azure Functions from {hastefuncapi_path}")
    
    # Parse hastefuncqueues  
    hastefuncqueues_path = os.path.join(api_dir, 'hastefuncqueues', 'function_app.py')
    if os.path.exists(hastefuncqueues_path):
        extractor.parse_source_file(hastefuncqueues_path)
        print(f"Parsed Azure Functions from {hastefuncqueues_path}")
    
    # Store extractor globally
    app._azure_function_extractor = extractor
    
    print(f"Azure Functions extractor initialized with {len(extractor.docstrings)} modules")


def setup(app):
    """Sphinx extension setup."""
    app.add_directive('azure-function', AzureFunctionDirective)
    app.add_directive('azure-function-module', AzureFunctionModuleDirective)
    
    # Set up the extractor immediately
    setup_azure_functions_extractor(app)
    
    return {
        'version': '1.0',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }

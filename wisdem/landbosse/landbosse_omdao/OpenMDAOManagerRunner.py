from collections import OrderedDict
import os

import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="numpy.ufunc size changed")
    import pandas as pd

from ..model import Manager
from .OpenMDAOFileOperations import OpenMDAOFileOperations
from .OpenMDAOInputDictGenerator import XlsxReader
from .XlsxGenerator import XlsxGenerator


class OpenMDAOManagerRunner:
    """
    This subclass implementation of XlsxManagerRunner runs all projects
    in a serial loop.
    """

    def __init__(self, file_ops=None):
        """
        The constructor simply creates an XlsxFileOperations instance
        to live throughout the lifetime of the instance

        Parameters
        ----------
        file_ops : OpenMDAOFileOperations
            The file operation instance used to create filenames. If this
            is left at the default of None, a new instance of
            XlsxFileOperations is created.
        """
        self.file_ops = file_ops if file_ops is not None else OpenMDAOFileOperations()

    def extract_module_type_operation_lists(self, runs_dict):
        """
        This method extract all the cost_by_module_type_operation lists for
        output in an Excel file.

        It finds values for the keys ending in '_module_type_operation'. It
        then concatenates them
        together so they can be easily written to a .csv or .xlsx

        Parameters
        ----------
        runs_dict : dict
            Values are the names of the projects. Keys are the lists of
            dictionaries that are lines for the .csv

        Returns
        -------
        list
            List of dicts to write to the .csv.
        """
        result = []
        for project_results in runs_dict.values():
            for key, value in project_results.items():
                if key.endswith('_module_type_operation'):
                    result.extend(value)
        return result

    def extract_details_lists(self, runs_dict):
        """
        This method extract all .csv lists from the OrderDict of runs to output
        into an Excel or .csv file.

        It finds values for the keys ending in '_csv'. It then concatenates them
        together so they can be easily written to a .csv, .xlsx or other
        columnar format. (The actual writing is left to other functions.

        Parameters
        ----------
        runs_dict : dict
            Values are the names of the projects. Keys are the lists of
            dictionaries that are lines for the .csv

        Returns
        -------
        list
            List of dicts to write to the .csv.
        """
        runs_for_csv = []
        for project_results in runs_dict.values():
            for key, value in project_results.items():
                if key.endswith('_csv'):
                    runs_for_csv.extend(value)
        return runs_for_csv

    def run_from_project_list_xlsx(self, projects_xlsx, enable_cost_and_scaling_modifications=False):
        """
        This function runs all the scenarios in the projects_xlsx file. It creates
        the OrderedDict that holds the results of all the runs. See the return
        section below for more details on what the OrderedDict contains.

        This is a concrete implementation of the super class method.

        Parameters
        ----------
        projects_xlsx : str
            A path name (preferably created with os.path.join()) specific to the
            operating system that is the main input .xlsx file that controls
            running of all the projects. Crucially, this file contains names of
            other. It is recommended that all input file be kept in the same
            input directory. Each line of projects_xlsx becomes a project_series.

        enable_cost_and_scaling_modifications : bool
            If True, this method modifies each row of the project list AFTER it has been
            modified by the parameters for to scale certain input values based
            on what has been parametrically modified.

        Returns
        -------
        OrderedDict, list, list, list
            First element of tuple is an ordered dict that is the result of
            all the runs. Each key is the name of a project and each value
            is the output dictionary of that project. The second element
            is the list of rows for the csv. The third element is the list
            of costs for the spreadsheets. The fourth element is the same as
            module_type_operation_lists, but every row has all the inputs
            on each row.
        """
        # Load the project list
        extended_project_list_before_parameter_modifications = self.read_project_and_parametric_list_from_xlsx()
        print('>>> Project and parametric lists loaded')

        # For file operations
        file_ops = OpenMDAOFileOperations()

        # Get the output dictionary ready
        runs_dict = OrderedDict()

        # Instantiate and XlsxReader to assemble master input dictionary
        xlsx_reader = XlsxReader()

        # Get a list ready to hold the project parameters after they have been modified
        # After all rows have been added to this list (each row is a series) then the
        # whole list will be transformed into a dataframe.
        #
        # See notes at https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.append.html
        # for why this is more performant than appending to a dataframe.
        extended_project_list_after_parameter_modifications = []

        # Loop over every project
        for _, project_parameters in extended_project_list_before_parameter_modifications.iterrows():

            # If project_parameters['Project ID with serial'] is null, that means there are no
            # parametric modifications to the project data dataframes. Hence,
            # just the plain Project ID without a serial number should be used.
            if pd.isnull(project_parameters['Project ID with serial']):
                project_id_with_serial = project_parameters['Project ID']
            else:
                project_id_with_serial = project_parameters['Project ID with serial']

            project_data_basename = project_parameters['Project data file']

            # Input path for unmodified project input data.
            project_data_xlsx = os.path.join(file_ops.landbosse_input_dir(), 'project_data', f'{project_data_basename}.xlsx')

            # Log each project
            print(f'<><><><><><><><><><><><><><><><><><> {project_id_with_serial} <><><><><><><><><><><><><><><><><><>')
            print('>>> project_id: {}'.format(project_id_with_serial))
            print('>>> Project data: {}'.format(project_data_xlsx))

            # Read the project data sheets.
            project_data_sheets = XlsxDataframeCache.read_all_sheets_from_xlsx(project_data_basename)

            # Transform the dataframes so that they have the right values for
            # the parametric variables.
            xlsx_reader.modify_project_data_and_project_list(project_data_sheets, project_parameters)

            # Apply cost and scaling modifications if needed.
            if enable_cost_and_scaling_modifications:
                xlsx_reader.apply_cost_and_scaling_modifications_to_project_parameters(project_parameters)

            # Append the modified project parameters
            extended_project_list_after_parameter_modifications.append(project_parameters)

            # Create the master input dictionary.
            master_input_dict = xlsx_reader.create_master_input_dictionary(project_data_sheets, project_parameters)

            # Now run the manager and accumulate its result into the runs_dict
            output_dict = dict()
            mc = Manager(input_dict=master_input_dict, output_dict=output_dict)
            mc.execute_landbosse(project_name=project_id_with_serial)
            output_dict['project_series'] = project_parameters
            runs_dict[project_id_with_serial] = output_dict

        final_result = dict()
        final_result['details_list'] = self.extract_details_lists(runs_dict)
        final_result['module_type_operation_list'] = self.extract_module_type_operation_lists(runs_dict)
        final_result['extended_project_list'] = pd.DataFrame(extended_project_list_after_parameter_modifications)

        # Return the runs for all the projects.
        return final_result

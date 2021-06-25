#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________
import os
from typing import List

import pandas as pd
from pyomo.core.base.set import UnknownSetDimen
from pyomo.repn import generate_standard_repn
from pyomo.solvers.plugins.solvers.gurobi_direct import GurobiDirect
from pyomo.environ import *


class MultiScenarioParamChange:
    def __init__(self, param, indexes, new_value):
        self.param = param
        self.indexes = indexes
        self.new_value = new_value
        self.old_value = None

    def apply_change(self, model):
        param = getattr(model, self.param)[self.indexes]
        if self.old_value is None:
            self.old_value = param.value
        param.value = self.new_value

    def undo_change(self, model):
        getattr(model, self.param)[self.indexes].value = self.old_value

class MultiScenario:
    def __init__(self, name, changes):
        self.name = name
        self.changes: List[MultiScenarioParamChange] = changes
        self.results = None
        self.model = None
        self.path = os.path.join(os.getcwd(), name)

    def __call__(self, model):
        """
        Call the instance will update it's model parameter
        """
        self.model = model
        return self

    def __enter__(self):
        # Apply parameter changes
        for change in self.changes:
            change.apply_change(self.model)

        if self.results is not None:
            for var in self.model.component_data_objects(
                    ctype=pyomo.core.base.var.Var,
                    descend_into=True,
                    active=True,
                    sort=False):
                if not var.stale:
                    var.value = self.results[var]

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Undo changes
        for change in self.changes:
            change.undo_change(self.model)

        if self.results is not None:
            for var in self.model.component_data_objects(
                    ctype=pyomo.core.base.var.Var,
                    descend_into=True,
                    active=True,
                    sort=False):
                if not var.stale:
                    var.value = None
        self.model = None


@SolverFactory.register('gurobi_scenarios', doc='Direct python interface to Gurobi')
class GurobiMultiScenarioSolver(GurobiDirect):
    DEBUG = False

    def __init__(self, *args, scenarios=None, **kwargs):
        super(GurobiMultiScenarioSolver, self).__init__(*args, **kwargs)
        self.scenarios: List[MultiScenario] = scenarios

    def _set_instance(self, model, kwds={}):
        """
        Set instance is called when the Gurobi model gets created.
        We override it to allow running _add_scenarios()
        """
        results = super(GurobiMultiScenarioSolver, self)._set_instance(model, kwds)
        self._add_scenarios(model)
        return results

    def _add_scenarios(self, model):
        gurobi_model = self._solver_model
        # Change number scenario
        gurobi_model.NumScenarios = len(self.scenarios)

        # Get the coefficients for our base case
        base_obj = generate_standard_repn(self._objective.expr, quadratic=True)

        # For each scenario
        print("Setting scenarios...")
        for i, scenario in enumerate(self.scenarios):
            # Select the scenario
            gurobi_model.Params.ScenarioNumber = i
            gurobi_model.ScenNName = scenario.name

            # Compute the scenario objective function
            with scenario(model):
                scenario_obj = generate_standard_repn(self._objective.expr, quadratic=True)

            # Verify that the coefficients are as expected
            if i == 0:
                if base_obj.linear_coefs != scenario_obj.linear_coefs:
                    raise Exception("First scenario should be the base scenario (no changes).")
                continue
            else:
                if base_obj.linear_coefs == scenario_obj.linear_coefs:
                    raise Exception(f"No difference in objective function"
                                    f" between scenario '{scenario.name}' and base scenario."
                                    f" This may be because the parameter that you expected to change"
                                    f" is used to define another parameter rather than being used in"
                                    f" an expression. You may need to change the model to use Expression()"
                                    f" rather than Param().")

            # If coefficients are different update Gurobi
            for base_coef, scenario_coef, pyomo_var in zip(
                    base_obj.linear_coefs,
                    scenario_obj.linear_coefs,
                    base_obj.linear_vars):
                if scenario_coef != base_coef:
                    if GurobiMultiScenarioSolver.DEBUG:
                        print(
                            f"{scenario.name}: Changing {pyomo_var.name} obj. coef. from {base_coef} to {scenario_coef}")
                    # Get the Gurobi variable
                    gurobi_var = self._pyomo_var_to_solver_var_map[pyomo_var]
                    # Update the coefficient
                    gurobi_var.ScenNObj = scenario_coef

                    # If debugging tag the variable so we can see it in the results.json
                    if GurobiMultiScenarioSolver.DEBUG:
                        gurobi_var.VTag = pyomo_var.name

    def _apply_solver(self, *args, **kwargs):
        """
        Called when Pyomo is ready to run the solver.
        Enabling debug will write the Gurobi problem and results files to allow inspection.
        """
        if GurobiMultiScenarioSolver.DEBUG:
            self._solver_model.write("problem.lp")
        results = super(GurobiMultiScenarioSolver, self)._apply_solver(*args, **kwargs)
        if GurobiMultiScenarioSolver.DEBUG:
            self._solver_model.write("results.json")
        return results

    def _load_vars(self, vars_to_load=None):
        """
        Called when loading variables back into model after solving.
        Overrides the default variable loading
        """
        # Get vars_to_load and gurobi variables
        var_map = self._pyomo_var_to_solver_var_map
        if vars_to_load is None:
            vars_to_load = var_map.keys()

        gurobi_vars_to_load = [var_map[pyomo_var] for pyomo_var in vars_to_load]

        # Mark variables as not stale
        ref_vars = self._referenced_variables
        for var in vars_to_load:
            if ref_vars[var] > 0:
                var.stale = False

        # For each scenario
        for i, scenario in enumerate(self.scenarios):
            # Retrieve the results from Gurobi
            self._solver_model.Params.ScenarioNumber = i
            vals = self._solver_model.getAttr("ScenNX", gurobi_vars_to_load)
            # Add them to the scenario results
            results = ComponentMap()
            for var, val in zip(vars_to_load, vals):
                if not var.stale:
                    results[var] = val
            self.scenarios[i].results = results


def load_inputs(mod, _, inputs_dir):
    """
    If a multiscenario.csv file exists, loads the inputs from that file
    """
    df = pd.read_csv(os.path.join(inputs_dir, "multi_scenario.csv"), index_col=False)
    assert (df.columns.values == ["scenario", "param", "value", "INDEX_1", "INDEX_2", "INDEX_3", "INDEX_4"]).all()

    scenarios = {}
    base_scenario_name = "Baseline"
    scenarios[base_scenario_name] = MultiScenario(base_scenario_name, [])

    for _, row in df.iterrows():
        scenario_name, param_name, value = row[0:3]
        if scenario_name == base_scenario_name:
            raise Exception(f"The scenario name {base_scenario_name} is reserverd.")
        if scenario_name not in scenarios:
            scenario = MultiScenario(scenario_name, [])
            scenarios[scenario_name] = scenario
        else:
            scenario = scenarios[scenario_name]
        param = getattr(mod, param_name)
        # TODO auto set mutability if possible
        if not param.mutable:
            raise Exception(f"Parameter {param_name} must be mutable. Set 'mutable=True'.")

        num_indexes = param.index_set().dimen
        if num_indexes == UnknownSetDimen:
            raise Exception(f"Index {param.name} has unknown dimension. Specify dimen= during its creation.")

        indexes = tuple(row[3:3 + num_indexes].values)

        change = MultiScenarioParamChange(param_name, indexes, value)
        scenario.changes.append(change)

    mod.scenarios = list(scenarios.values())

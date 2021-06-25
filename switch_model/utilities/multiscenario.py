#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

import logging
from typing import List

from pyomo.environ import *
from pyomo.common.collections import ComponentMap
from pyomo.repn import generate_standard_repn
from pyomo.opt.base import SolverFactory
from pyomo.solvers.plugins.solvers.gurobi_direct import GurobiDirect

logger = logging.getLogger('pyomo.solvers')


def _is_numeric(x):
    try:
        float(x)
    except ValueError:
        return False
    return True


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
        self.results = ComponentMap()
        self.model = None

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

        if len(self.results) != 0:
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

        if len(self.results) != 0:
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
        old_obj = generate_standard_repn(model.SystemCost.expr, quadratic=True)

        # For each scenario
        print("Setting scenarios...")
        for i, scenario in enumerate(self.scenarios):
            # Select the scenario
            gurobi_model.Params.ScenarioNumber = i
            gurobi_model.ScenNName = scenario.name

            # Compute the scenario objective function
            with scenario(model):
                new_obj = generate_standard_repn(model.SystemCost.expr, quadratic=True)

            if i == 0:
                if old_obj.linear_coefs != new_obj.linear_coefs:
                    raise Exception("First scenario should be the base scenario (no changes).")
            else:
                if old_obj.linear_coefs == new_obj.linear_coefs:
                    raise Exception(f"No difference in objective function"
                                  f" between scenario '{scenario.name}' and base scenario."
                                  f" This may be because the parameter that you expected to change"
                                  f" is used to define another parameter rather than being used in"
                                  f" an expression. You may need to change the model to use Expression()"
                                  f" rather than Param().")

            # If coefficients are different update Gurobi
            for old_coef, new_coef, pyomo_var in zip(old_obj.linear_coefs, new_obj.linear_coefs, old_obj.linear_vars):
                if new_coef != old_coef:
                    print(f"{scenario.name}: Changing {pyomo_var.name} obj. coef. from {old_coef} to {new_coef}")
                    gurobi_var = self._pyomo_var_to_solver_var_map[pyomo_var]
                    gurobi_var.ScenNObj = new_coef
                    gurobi_var.VTag = pyomo_var.name

    # def _apply_solver(self, *args, **kwargs):
    #     self._solver_model.write("problem.lp")
    #     results = super(GurobiMultiScenarioSolver, self)._apply_solver(*args, **kwargs)
    #     self._solver_model.write("results.json")
    #     return results

    def _load_vars(self, vars_to_load=None):
        """
        Called when loading variables back into model after solving
        """
        var_map = self._pyomo_var_to_solver_var_map
        ref_vars = self._referenced_variables
        if vars_to_load is None:
            vars_to_load = var_map.keys()

        gurobi_vars_to_load = [var_map[pyomo_var] for pyomo_var in vars_to_load]
        vals = self._solver_model.getAttr("X", gurobi_vars_to_load)

        for var, val in zip(vars_to_load, vals):
            if ref_vars[var] > 0:
                var.stale = False

        for i, scenario in enumerate(self.scenarios):
            self._solver_model.Params.ScenarioNumber = i
            vals = self._solver_model.getAttr("ScenNX", gurobi_vars_to_load)
            for var, val in zip(vars_to_load, vals):
                if not var.stale:
                    self.scenarios[i].results[var] = val

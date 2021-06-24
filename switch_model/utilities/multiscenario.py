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


class DegreeError(ValueError):
    pass


def _is_numeric(x):
    try:
        float(x)
    except ValueError:
        return False
    return True

"""
min 
Minimize_System_Cost:
+10.673275513518735 BuildGen(Battery_Storage_2020)
+1885.8523792992839 BuildGen(S_Central_PV_1_2020)
+3193.6947082588722 BuildGen(S_Geothermal_1998)
+3193.6947082588722 BuildGen(S_Geothermal_2020)
+0.99718942035373992 BuildStorageEnergy(Battery_Storage_2020)
+0.30697836004187801 DispatchGen(Battery_Storage_1)
+0.30697836004187801 DispatchGen(Battery_Storage_2)
+885.01861200073427 DispatchGen(S_Geothermal_1)
+885.01861200073427 DispatchGen(S_Geothermal_2)
"""


class MultiScenario:
    def __init__(self, name, changes):
        self.name = name
        self.changes = changes
        self.results = ComponentMap()


@SolverFactory.register('gurobi_scenarios', doc='Direct python interface to Gurobi')
class GurobiMultiScenarioSolver(GurobiDirect):
    def __init__(self, *args, scenarios=None, **kwargs):
        super(GurobiMultiScenarioSolver, self).__init__(*args, **kwargs)
        self.scenarios: List[MultiScenario] = scenarios

    def _set_instance(self, model, kwds={}):
        """
        Set instance is called when the model gets created.
        """
        res = super(GurobiMultiScenarioSolver, self)._set_instance(model, kwds)
        self._add_scenarios(model)
        return res

    def _add_scenarios(self, model):
        gurobi_model = self._solver_model
        # Change number scenario
        gurobi_model.NumScenarios = len(self.scenarios)

        old_obj = self._get_objective()

        for i, scenario in enumerate(self.scenarios):
            gurobi_model.Params.ScenarioNumber = i
            gurobi_model.ScenNName = scenario.name

            # Apply parameter changes
            for (name, indexes, value) in scenario.changes:
                param = getattr(model, name)
                if not hasattr(param, "initial_val"):
                    param.initial_val = param[indexes]
                    # TODO undo changes to params
                    pass
                param[indexes] = value

            # Compute objective function
            new_obj = self._get_objective()

            # See diff
            changes = []
            for i1, coef in enumerate(old_obj.linear_coefs):
                new_coef = new_obj.linear_coefs[i1]
                if new_coef != coef:
                    changes.append((old_obj.linear_vars[i1], new_coef))

            # Set diff as scenario
            for (pyomo_var, val) in changes:
                gurobi_var = self._pyomo_var_to_solver_var_map[pyomo_var]
                gurobi_var.ScenNObj = val
                pass

    def _get_objective(self):
        return generate_standard_repn(self._objective.expr, quadratic=True)

    def _load_vars(self, vars_to_load=None):
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


def load_multi_scenario(instance, scenario: MultiScenario):
    for var in instance.component_data_objects(ctype=pyomo.core.base.var.Var,
                                               descend_into=True,
                                               active=True,
                                               sort=False):
        if not var.stale:
            var.value = scenario.results[var]

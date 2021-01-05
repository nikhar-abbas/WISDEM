import numpy as np
import openmdao.api as om
import wisdem.commonse.utilities as util
import wisdem.pyframe3dd.pyframe3dd as pyframe3dd
from wisdem.commonse import gravity
from wisdem.floatingse.member import Member

NNODES_MAX = 1000
NELEM_MAX = 1000
NULL = -9999
RIGID = 1e30

# TODO:
# - Added mass, hydro stiffness?
# - Stress or buckling?


class PlatformFrame(om.ExplicitComponent):
    def initialize(self):
        self.options.declare("options")

    def setup(self):
        opt = self.options["options"]
        n_member = opt["floating"]["n_member"]

        for k in range(n_member):
            self.add_input("member" + str(k) + ":nodes_xyz", shape_by_conn=True, units="m")
            self.add_input("member" + str(k) + ":nodes_r", shape_by_conn=True, units="m")
            self.add_input("member" + str(k) + ":section_A", shape_by_conn=True, units="m**2")
            self.add_input("member" + str(k) + ":section_Asx", shape_by_conn=True, units="m**2")
            self.add_input("member" + str(k) + ":section_Asy", shape_by_conn=True, units="m**2")
            self.add_input("member" + str(k) + ":section_Ixx", shape_by_conn=True, units="kg*m**2")
            self.add_input("member" + str(k) + ":section_Iyy", shape_by_conn=True, units="kg*m**2")
            self.add_input("member" + str(k) + ":section_Izz", shape_by_conn=True, units="kg*m**2")
            self.add_input("member" + str(k) + ":section_rho", shape_by_conn=True, units="kg/m**3")
            self.add_input("member" + str(k) + ":section_E", shape_by_conn=True, units="Pa")
            self.add_input("member" + str(k) + ":section_G", shape_by_conn=True, units="Pa")
            self.add_discrete_input("member" + str(k) + ":idx_cb", 0)
            self.add_input("member" + str(k) + ":buoyancy_force", 0.0, units="N")
            self.add_input("member" + str(k) + ":displacement", 0.0, units="m**3")
            self.add_input("member" + str(k) + ":center_of_buoyancy", np.zeros(3), units="m")
            self.add_input("member" + str(k) + ":center_of_mass", np.zeros(3), units="m")
            self.add_input("member" + str(k) + ":total_mass", 0.0, units="kg")
            self.add_input("member" + str(k) + ":total_cost", 0.0, units="USD")
            self.add_input("member" + str(k) + ":Awater", 0.0, units="m**2")
            self.add_input("member" + str(k) + ":Iwater", 0.0, units="m**4")
            self.add_input("member" + str(k) + ":added_mass", np.zeros(6), units="kg")

        self.add_output("platform_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_output("platform_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_output("platform_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_output("platform_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_output("platform_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_output("platform_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("platform_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("platform_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("platform_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("platform_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("platform_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("platform_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_output("platform_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_output("platform_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_output("platform_displacement", 0.0, units="m**3")
        self.add_output("platform_center_of_buoyancy", np.zeros(3), units="m")
        self.add_output("platform_center_of_mass", np.zeros(3), units="m")
        self.add_output("platform_mass", 0.0, units="kg")
        self.add_output("platform_cost", 0.0, units="USD")
        self.add_output("platform_Awater", 0.0, units="m**2")
        self.add_output("platform_Iwater", 0.0, units="m**4")
        self.add_output("platform_added_mass", np.zeros(6), units="kg")

        self.node_mem2glob = {}
        # self.node_glob2mem = {}

    def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
        # This shouldn't change during an optimization, so save some time?
        if len(self.node_mem2glob) == 0:
            self.set_connectivity(inputs, outputs, discrete_inputs, discrete_outputs)

        self.set_node_props(inputs, outputs, discrete_inputs, discrete_outputs)
        self.set_element_props(inputs, outputs)

    def set_connectivity(self, inputs, outputs, discrete_inputs, discrete_outputs):
        # Load in number of members
        opt = self.options["options"]
        n_member = opt["floating"]["n_member"]

        # Initialize running lists across all members
        nodes_temp = np.empty((0, 3))
        elem_n1 = np.array([], dtype=np.int_)
        elem_n2 = np.array([], dtype=np.int_)

        # Look over members and grab all nodes and internal connections
        for k in range(n_member):
            inode_xyz = inputs["member" + str(k) + ":nodes_xyz"]
            inodes = inode_xyz.shape[0]
            inode_range = np.arange(inodes - 1)

            n = nodes_temp.shape[0]
            for ii in range(inodes):
                self.node_mem2glob[(k, ii)] = n + ii

            elem_n1 = np.append(elem_n1, n + inode_range)
            elem_n2 = np.append(elem_n2, n + inode_range + 1)
            nodes_temp = np.append(nodes_temp, inode_xyz, axis=0)

        # Reveal connectivity by using mapping to unique node positions
        nodes, idx, inv = np.unique(nodes_temp.round(4), axis=0, return_index=True, return_inverse=True)
        nnode = nodes.shape[0]
        outputs["platform_nodes"] = NULL * np.ones((NNODES_MAX, 3))
        outputs["platform_nodes"][:nnode, :] = nodes

        # Use mapping to set references to node joints
        nelem = elem_n1.size
        discrete_outputs["platform_elem_n1"] = NULL * np.ones(NELEM_MAX, dtype=np.int_)
        discrete_outputs["platform_elem_n2"] = NULL * np.ones(NELEM_MAX, dtype=np.int_)
        discrete_outputs["platform_elem_n1"][:nelem] = inv[elem_n1]
        discrete_outputs["platform_elem_n2"][:nelem] = inv[elem_n2]

        # Update global 2 member mappings
        for k in self.node_mem2glob.keys():
            self.node_mem2glob[k] = inv[self.node_mem2glob[k]]

    def set_node_props(self, inputs, outputs, discrete_inputs, discrete_outputs):
        # Load in number of members
        opt = self.options["options"]
        n_member = opt["floating"]["n_member"]

        # Number of valid nodes
        nnode = np.where(outputs["platform_nodes"][:, 0] == NULL)[0][0]

        # Find greatest radius of all members at node intersections
        Rnode = np.zeros(nnode)
        for k in range(n_member):
            irnode = inputs["member" + str(k) + ":nodes_r"]
            n = irnode.shape[0]
            for ii in range(n):
                iglob = self.node_mem2glob[(k, ii)]
                Rnode[iglob] = np.array([Rnode[iglob], irnode[ii]]).max()

        # Find forces on nodes
        Fnode = np.zeros((nnode, 3))
        for k in range(n_member):
            icb = discrete_inputs["member" + str(k) + ":idx_cb"]
            iglob = self.node_mem2glob[(k, icb)]
            Fnode[iglob, 2] += inputs["member" + str(k) + ":buoyancy_force"]

        # Store outputs
        outputs["platform_Rnode"] = NULL * np.ones(NNODES_MAX)
        outputs["platform_Rnode"][:nnode] = Rnode
        outputs["platform_Fnode"] = NULL * np.ones((NNODES_MAX, 3))
        outputs["platform_Fnode"][:nnode, :] = Fnode

    def set_element_props(self, inputs, outputs):
        # Load in number of members
        opt = self.options["options"]
        n_member = opt["floating"]["n_member"]

        # Initialize running lists across all members
        elem_A = np.array([])
        elem_Asx = np.array([])
        elem_Asy = np.array([])
        elem_Ixx = np.array([])
        elem_Iyy = np.array([])
        elem_Izz = np.array([])
        elem_rho = np.array([])
        elem_E = np.array([])
        elem_G = np.array([])

        mass = 0.0
        cost = 0.0
        volume = 0.0
        Awater = 0.0
        Iwater = 0.0
        m_added = np.zeros(6)
        cg_plat = np.zeros(3)
        cb_plat = np.zeros(3)

        # Append all member data
        for k in range(n_member):
            elem_A = np.append(elem_A, inputs["member" + str(k) + ":section_A"])
            elem_Asx = np.append(elem_Asx, inputs["member" + str(k) + ":section_Asx"])
            elem_Asy = np.append(elem_Asy, inputs["member" + str(k) + ":section_Asy"])
            elem_Ixx = np.append(elem_Ixx, inputs["member" + str(k) + ":section_Ixx"])
            elem_Iyy = np.append(elem_Iyy, inputs["member" + str(k) + ":section_Iyy"])
            elem_Izz = np.append(elem_Izz, inputs["member" + str(k) + ":section_Izz"])
            elem_rho = np.append(elem_rho, inputs["member" + str(k) + ":section_rho"])
            elem_E = np.append(elem_E, inputs["member" + str(k) + ":section_E"])
            elem_G = np.append(elem_G, inputs["member" + str(k) + ":section_G"])

            # Mass, volume, cost tallies
            imass = inputs["member" + str(k) + ":total_mass"]
            ivol = inputs["member" + str(k) + ":displacement"]

            mass += imass
            volume += ivol
            cost += inputs["member" + str(k) + ":total_cost"]
            Awater += inputs["member" + str(k) + ":Awater"]
            Iwater += inputs["member" + str(k) + ":Iwater"]
            m_added += inputs["member" + str(k) + ":added_mass"]

            # Center of mass / buoyancy tallies
            cg_plat += imass * inputs["member" + str(k) + ":center_of_mass"]
            cb_plat += ivol * inputs["member" + str(k) + ":center_of_buoyancy"]

        # Store outputs
        nelem = elem_A.size
        outputs["platform_elem_A"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_Asx"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_Asy"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_Ixx"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_Iyy"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_Izz"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_rho"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_E"] = NULL * np.ones(NELEM_MAX)
        outputs["platform_elem_G"] = NULL * np.ones(NELEM_MAX)

        outputs["platform_elem_A"][:nelem] = elem_A
        outputs["platform_elem_Asx"][:nelem] = elem_Asx
        outputs["platform_elem_Asy"][:nelem] = elem_Asy
        outputs["platform_elem_Ixx"][:nelem] = elem_Ixx
        outputs["platform_elem_Iyy"][:nelem] = elem_Iyy
        outputs["platform_elem_Izz"][:nelem] = elem_Izz
        outputs["platform_elem_rho"][:nelem] = elem_rho
        outputs["platform_elem_E"][:nelem] = elem_E
        outputs["platform_elem_G"][:nelem] = elem_G

        outputs["platform_mass"] = mass
        outputs["platform_cost"] = cost
        outputs["platform_displacement"] = volume
        outputs["platform_center_of_mass"] = cg_plat / mass
        outputs["platform_center_of_buoyancy"] = cb_plat / volume
        outputs["platform_Awater"] = Awater
        outputs["platform_Iwater"] = Iwater
        outputs["platform_added_mass"] = m_added


class TowerPreMember(om.ExplicitComponent):
    def setup(self):
        self.add_input("transition_node", np.zeros(3), units="m")
        self.add_input("hub_height", np.zeros(3), units="m")
        self.add_output("hub_node", np.zeros(3), units="m")

    def compute(self, inputs, outputs):
        transition_node = inputs["transition_node"]
        hub_node = transition_node
        hub_node[2] = inputs["hub_height"]
        outputs["hub_node"] = hub_node


class PlatformTowerFrame(om.ExplicitComponent):
    def setup(self):

        self.add_input("platform_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_input("platform_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_input("platform_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_input("platform_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_input("platform_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_input("platform_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("platform_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("platform_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("platform_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("platform_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("platform_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("platform_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_input("platform_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("platform_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("platform_center_of_mass", np.zeros(3), units="m")
        self.add_input("platform_mass", 0.0, units="kg")

        self.add_input("tower_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_input("tower_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_input("tower_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_input("tower_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_input("tower_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_input("tower_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_input("tower_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("tower_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("tower_center_of_mass", np.zeros(3), units="m")
        self.add_input("tower_mass", 0.0, units="kg")

        self.add_input("transition_node", np.zeros(3), units="m")
        self.add_input("transition_piece_mass", 0.0, units="kg")
        self.add_input("rna_mass", 0.0, units="kg")
        self.add_input("rna_cg", np.zeros(3), units="m")

        self.add_output("system_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_output("system_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_output("system_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_output("system_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_output("system_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_output("system_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("system_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("system_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_output("system_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("system_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("system_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_output("system_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_output("system_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_output("system_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_output("system_center_of_mass", np.zeros(3), units="m")
        self.add_output("system_mass", 0.0, units="kg")

    def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):

        node_platform = inputs["platform_nodes"]
        node_tower = inputs["tower_nodes"]

        nnode_platform = np.where(node_platform[:, 0] == NULL)[0][0]
        nnode_tower = np.where(node_tower[:, 0] == NULL)[0][0]
        nnode_system = nnode_platform + nnode_tower - 1

        nelem_platform = np.where(inputs["platform_elem_A"] == NULL)[0][0]
        nelem_tower = np.where(inputs["tower_elem_A"] == NULL)[0][0]
        nelem_system = nelem_platform + nelem_tower

        itrans_platform = util.closest_node(node_platform, inputs["transition_node"])
        tower_n1 = discrete_inputs["tower_elem_n1"][:nelem_tower] + nnode_platform - 1
        tower_n2 = discrete_inputs["tower_elem_n2"][:nelem_tower] + nnode_platform - 1
        tower_n1[0] = itrans_platform

        outputs["system_nodes"] = NULL * np.ones((NNODES_MAX, 3))
        outputs["system_Fnode"] = NULL * np.ones((NNODES_MAX, 3))
        outputs["system_Rnode"] = NULL * np.ones(NNODES_MAX)
        discrete_outputs["system_elem_n1"] = NULL * np.ones(NELEM_MAX, dtype=np.int_)
        discrete_outputs["system_elem_n2"] = NULL * np.ones(NELEM_MAX, dtype=np.int_)

        outputs["system_nodes"][:nnode_system, :] = np.vstack(
            (node_platform[:nnode_platform, :], node_tower[1:nnode_tower, :])
        )
        outputs["system_Fnode"][:nnode_system, :] = np.vstack(
            (inputs["platform_Fnode"][:nnode_platform, :], inputs["tower_Fnode"][1:nnode_tower, :])
        )
        outputs["system_Rnode"][:nnode_system] = np.r_[
            inputs["platform_Rnode"][:nnode_platform], inputs["tower_Rnode"][1:nnode_tower]
        ]

        discrete_outputs["system_elem_n1"][:nelem_system] = np.r_[
            discrete_inputs["platform_elem_n1"][:nelem_platform],
            tower_n1,
        ]
        discrete_outputs["system_elem_n2"][:nelem_system] = np.r_[
            discrete_inputs["platform_elem_n2"][:nelem_platform],
            tower_n2,
        ]

        for var in [
            "elem_A",
            "elem_Asx",
            "elem_Asy",
            "elem_Ixx",
            "elem_Iyy",
            "elem_Izz",
            "elem_rho",
            "elem_E",
            "elem_G",
        ]:
            outputs["system_" + var] = NULL * np.ones(NELEM_MAX)
            outputs["system_" + var][:nelem_system] = np.r_[
                inputs["platform_" + var][:nelem_platform], inputs["tower_" + var][:nelem_tower]
            ]

        outputs["system_mass"] = (
            inputs["platform_mass"] + inputs["tower_mass"] + inputs["rna_mass"] + inputs["transition_piece_mass"]
        )
        outputs["system_center_of_mass"] = (
            inputs["platform_mass"] * inputs["platform_center_of_mass"]
            + inputs["tower_mass"] * inputs["tower_center_of_mass"]
            + inputs["rna_mass"] * (inputs["rna_cg"] + inputs["hub_node"])
            + inputs["transition_piece_mass"] * inputs["transition_node"]
        ) / outputs["system_mass"]

        outputs["variable_ballast_mass"] = (
            inputs["platform_displacement"] * inputs["rho_water"] - outputs["system_mass"]
        )


class FrameAnalysis(om.ExplicitComponent):
    def initialize(self):
        self.options.declare("options")

    def setup(self):
        opt = self.options["options"]
        n_nodes = opt["mooring"]["n_nodes"]

        self.add_input("tower_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_input("tower_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_input("tower_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_input("tower_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_input("tower_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_input("tower_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("tower_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("tower_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_input("tower_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("tower_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")

        self.add_input("system_nodes", NULL * np.ones((NNODES_MAX, 3)), units="m")
        self.add_input("system_Fnode", NULL * np.ones((NNODES_MAX, 3)), units="N")
        self.add_input("system_Rnode", NULL * np.ones(NNODES_MAX), units="m")
        self.add_discrete_input("system_elem_n1", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_discrete_input("system_elem_n2", NULL * np.ones(NELEM_MAX, dtype=np.int_))
        self.add_input("system_elem_A", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("system_elem_Asx", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("system_elem_Asy", NULL * np.ones(NELEM_MAX), units="m**2")
        self.add_input("system_elem_Ixx", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("system_elem_Iyy", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("system_elem_Izz", NULL * np.ones(NELEM_MAX), units="kg*m**2")
        self.add_input("system_elem_rho", NULL * np.ones(NELEM_MAX), units="kg/m**3")
        self.add_input("system_elem_E", NULL * np.ones(NELEM_MAX), units="Pa")
        self.add_input("system_elem_G", NULL * np.ones(NELEM_MAX), units="Pa")

        self.add_input("transition_node", np.zeros(3), units="m")
        self.add_input("transition_piece_mass", 0.0, units="kg")
        self.add_input("transition_piece_I", np.zeros(6), units="kg*m**2")
        self.add_input("rna_mass", 0.0, units="kg")
        self.add_input("rna_cg", np.zeros(3), units="m")
        self.add_input("rna_I", np.zeros(6), units="kg*m**2")
        self.add_input("mooring_neutral_load", np.zeros((n_nodes, 3)), units="N")
        self.add_input("mooring_fairlead_joints", np.zeros((n_nodes, 3)), units="m")

    def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):

        # Unpack variables
        n_lines = self.options["options"]["mooring"]["n_lines"]
        I_trans = inputs["transition_piece_I"]
        m_rna = inputs["rna_mass"]
        cg_rna = inputs["rna_cg"]
        I_rna = inputs["rna_I"]

        fairlead_joints = inputs["mooring_fairlead_joints"]
        mooringF = inputs["mooring_neutral_load"]

        # Create frame3dd instance: nodes, elements, reactions, and options
        for frame in ["tower", "system"]:
            nodes = inputs[frame + "_nodes"]
            nnode = np.where(nodes[:, 0] == NULL)[0][0]
            nodes = nodes[:nnode, :]
            rnode = inputs[frame + "_Rnode"][:nnode]
            Fnode = inputs[frame + "_Fnode"][:nnode, :]
            Mnode = np.zeros((nnode, 3))
            ihub = np.argmax(nodes[:, 2]) - 1
            itrans = util.closest_node(nodes, inputs["transition_node"])

            N1 = discrete_inputs[frame + "_elem_n1"]
            nelem = np.where(N1 == NULL)[0][0]
            N1 = N1[:nelem]
            N2 = discrete_inputs[frame + "_elem_n2"][:nelem]
            A = inputs[frame + "_elem_A"][:nelem]
            Asx = inputs[frame + "_elem_Asx"][:nelem]
            Asy = inputs[frame + "_elem_Asy"][:nelem]
            Ixx = inputs[frame + "_elem_Ixx"][:nelem]
            Iyy = inputs[frame + "_elem_Iyy"][:nelem]
            Izz = inputs[frame + "_elem_Izz"][:nelem]
            rho = inputs[frame + "_elem_rho"][:nelem]
            E = inputs[frame + "_elem_E"][:nelem]
            G = inputs[frame + "_elem_G"][:nelem]
            roll = np.zeros(nelem)

            inodes = np.arange(nnode) + 1
            node_obj = pyframe3dd.NodeData(inodes, nodes[:, 0], nodes[:, 1], nodes[:, 2], rnode)

            ielem = np.arange(nelem) + 1
            elem_obj = pyframe3dd.ElementData(ielem, N1 + 1, N2 + 1, A, Asx, Asy, Izz, Ixx, Iyy, E, G, roll, rho)

            # TODO: Hydro_K + Mooring_K for tower (system too?)
            rid = np.array([itrans])  # np.array([np.argmin(nodes[:, 2])])
            Rx = Ry = Rz = Rxx = Ryy = Rzz = np.array([RIGID])
            react_obj = pyframe3dd.ReactionData(rid + 1, Rx, Ry, Rz, Rxx, Ryy, Rzz, rigid=RIGID)

            frame3dd_opt = self.options["options"]["floating"]["frame3dd"]
            opt_obj = pyframe3dd.Options(frame3dd_opt["shear"], frame3dd_opt["geom"], -1.0)

            myframe = pyframe3dd.Frame(node_obj, react_obj, elem_obj, opt_obj)

            # Added mass
            if frame == "tower":
                # TODO: Added mass and stiffness
                m_trans = inputs["transition_piece_mass"]  # + inputs["platform_mass"]
                cg_trans = inputs["transition_node"] - inputs["platform_center_of_mass"]
            else:
                m_trans = inputs["transition_piece_mass"]
                cg_trans = np.zeros(3)
            add_gravity = True
            mID = np.array([itrans, ihub], dtype=np.int_)
            m_add = np.array([m_trans, m_rna])
            I_add = np.c_[I_trans, I_rna]
            cg_add = np.c_[cg_trans, cg_rna]
            myframe.changeExtraNodeMass(
                mID + 1,
                m_add,
                I_add[0, :],
                I_add[1, :],
                I_add[2, :],
                I_add[3, :],
                I_add[4, :],
                I_add[5, :],
                cg_add[0, :],
                cg_add[1, :],
                cg_add[2, :],
                add_gravity,
            )

            # Dynamics
            Mmethod = 1
            lump = 0
            shift = 0.0
            myframe.enableDynamics(10, Mmethod, lump, frame3dd_opt["tol"], shift)

            # Initialize loading with gravity, mooring line forces, and buoyancy (already in nodal forces)
            gx = gy = 0.0
            gz = -gravity
            load_obj = pyframe3dd.StaticLoadCase(gx, gy, gz)

            if frame == "system":
                for k in range(n_lines):
                    ind = util.closest_node(nodes, fairlead_joints[k, :])
                    Fnode[ind, :] += mooringF[k, :]
            Fnode[ihub, :] += inputs["rna_F"]
            Mnode[ihub, :] += inputs["rna_M"]
            nF = np.where(np.abs(Fnode).sum(axis=1) > 0.0)[0]
            load_obj.changePointLoads(
                nF + 1, Fnode[nF, 0], Fnode[nF, 1], Fnode[nF, 2], Mnode[nF, 0], Mnode[nF, 1], Mnode[nF, 2]
            )

            # Add the load case and run
            myframe.addLoadCase(load_obj)
            # myframe.write('temp.3dd')
            displacements, forces, reactions, internalForces, mass, modal = myframe.run()

            # Determine needed variable ballast
            F_sum = -1.0 * np.array([reactions.Fx.sum(), reactions.Fy.sum(), reactions.Fz.sum()])
            M_sum = -1.0 * np.array([reactions.Mxx.sum(), reactions.Myy.sum(), reactions.Mzz.sum()])
            L = np.sqrt(np.sum((nodes[N2, :] - nodes[N1, :]) ** 2, axis=1))


class FloatingFrame(om.Group):
    def initialize(self):
        self.options.declare("modeling_options")

    def setup(self):
        opt = self.options["modeling_options"]

        self.add_subsystem("plat", PlatformFrame(options=opt), promotes=["*"])
        self.add_subsystem("pre", TowerPreMember(), promotes=["*"])

        prom = [
            "E_mat",
            "G_mat",
            "sigma_y_mat",
            "rho_mat",
            "rho_water",
            "unit_cost_mat",
            "material_names",
            "painting_cost_rate",
            "labor_cost_rate",
        ]
        prom += [
            ("nodes_xyz", "tower_nodes"),
            ("nodes_r", "tower_Rnode"),
            ("total_mass", "tower_mass"),
            ("total_cost", "tower_cost"),
            ("center_of_mass", "tower_center_of_mass"),
            ("joint1", "transition_node"),
            ("joint2", "hub_node"),
        ]
        for var in ["A", "Asx", "Asy", "rho", "Ixx", "Iyy", "Izz", "E", "G"]:
            prom += [("section_" + var, "tower_" + var)]
        self.add_subsystem(
            "tower", Member(modeling_options=opt, member_options=opt["floating"]["tower"]), promotes=prom
        )

        self.add_subsystem("mux", PlatformTowerFrame(), promotes=["*"])
        self.add_subsystem("frame", FrameAnalysis(options=opt), promotes=["*"])

        # self.connect("transition_node", "tower.joint1")
        # self.connect("hub_node", "tower.joint2")

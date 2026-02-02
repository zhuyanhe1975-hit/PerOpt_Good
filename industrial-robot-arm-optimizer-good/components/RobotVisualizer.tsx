
import React, { useRef, useEffect } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';
import URDFLoader from 'urdf-loader';
import { AssetMap, OptimizationResult } from '../types';

interface RobotVisualizerProps {
  urdfContent: string | null;
  metrics: OptimizationResult;
  assets: AssetMap;
  isOptimizing: boolean;
  basePath?: string;
}

const RobotVisualizer: React.FC<RobotVisualizerProps> = ({ urdfContent, metrics, assets, isOptimizing, basePath }) => {
  const mountRef = useRef<HTMLDivElement>(null);
  const actualRobotRef = useRef<any>(null);
  const phantomRobotRef = useRef<any>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);

  const isOptimizingRef = useRef(isOptimizing);

  useEffect(() => {
    isOptimizingRef.current = isOptimizing;
  }, [isOptimizing]);

  useEffect(() => {
    if (!mountRef.current || !urdfContent) return;

    const width = mountRef.current.clientWidth || 800;
    const height = mountRef.current.clientHeight || 600;

    const disposeObject = (obj: THREE.Object3D | null) => {
      if (!obj) return;
      obj.traverse((child) => {
        const mesh = child as unknown as THREE.Mesh;
        if (!(mesh as any).isMesh) return;
        if (mesh.geometry) mesh.geometry.dispose();
        const mat = mesh.material as unknown as THREE.Material | THREE.Material[];
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose();
      });
    };

    const createRobotMaterial = (opts: { color: number; isPhantom: boolean }) => {
      const material = new THREE.MeshStandardMaterial({
        color: opts.color,
        metalness: opts.isPhantom ? 0.0 : 0.25,
        roughness: opts.isPhantom ? 0.25 : 0.6,
        transparent: opts.isPhantom,
        opacity: opts.isPhantom ? 0.22 : 1.0,
        depthWrite: !opts.isPhantom,
        depthTest: !opts.isPhantom ? true : false,
        emissive: opts.isPhantom ? new THREE.Color(0x10b981) : new THREE.Color(0x000000),
        emissiveIntensity: opts.isPhantom ? 0.35 : 0.0,
      });

      if (opts.isPhantom) {
        material.polygonOffset = true;
        material.polygonOffsetFactor = -2;
        material.polygonOffsetUnits = -2;
      }

      return material;
    };

    const applyRobotMaterial = (robot: THREE.Object3D, material: THREE.Material, isPhantom: boolean) => {
      robot.traverse((child) => {
        const mesh = child as unknown as THREE.Mesh;
        if (!(mesh as any).isMesh) return;
        mesh.material = material;
        mesh.castShadow = !isPhantom;
        mesh.receiveShadow = !isPhantom;
      });
    };

    const scene = new THREE.Scene();
    sceneRef.current = scene;
    scene.background = new THREE.Color(0x0a0a0b);
    
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.01, 100);
    cameraRef.current = camera;
    camera.position.set(1.5, 1.5, 1.5);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    mountRef.current.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controlsRef.current = controls;
    controls.enableDamping = true;

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const mainLight = new THREE.DirectionalLight(0xffffff, 1.2);
    mainLight.position.set(2, 5, 2);
    mainLight.castShadow = true;
    scene.add(mainLight);

    const grid = new THREE.GridHelper(5, 10, 0x27272a, 0x18181b);
    scene.add(grid);

    const manager = new THREE.LoadingManager();
    const stlLoader = new STLLoader(manager);
    const urdfLoader = new URDFLoader(manager);

    const actualMaterial = createRobotMaterial({ color: 0x94a3b8, isPhantom: false });
    const phantomMaterial = createRobotMaterial({ color: 0x10b981, isPhantom: true });

    // TCP markers (actual + phantom)
    const tcpActualMat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.1, roughness: 0.2, emissive: new THREE.Color(0xffffff), emissiveIntensity: 0.15 });
    const tcpPhantomMat = new THREE.MeshStandardMaterial({ color: 0x10b981, metalness: 0.0, roughness: 0.2, transparent: true, opacity: 0.35, emissive: new THREE.Color(0x10b981), emissiveIntensity: 0.6, depthWrite: false });
    const tcpGeo = new THREE.SphereGeometry(0.02, 18, 18);
    const tcpActual = new THREE.Mesh(tcpGeo, tcpActualMat);
    const tcpPhantom = new THREE.Mesh(tcpGeo, tcpPhantomMat);
    tcpActual.renderOrder = 10;
    tcpPhantom.renderOrder = 11;
    scene.add(tcpActual);
    scene.add(tcpPhantom);
    tcpPhantom.visible = false;

    const computeTcpWorldPosition = (robot: any) => {
      const pos = new THREE.Vector3();
      if (!robot) return { ok: false as const, pos };

      const links: Record<string, any> | undefined = robot.links;
      if (links && typeof links === 'object') {
        const names = Object.keys(links);
        const preferredPatterns = [/tool/i, /tcp/i, /ee/i, /end/i, /link_6/i, /link6/i, /l6/i, /wrist/i];
        for (const pat of preferredPatterns) {
          const hit = names.find((n) => pat.test(n));
          if (hit && links[hit]?.getWorldPosition) {
            links[hit].getWorldPosition(pos);
            return { ok: true as const, pos };
          }
        }

        const baseName = names[0];
        const basePos = new THREE.Vector3();
        if (baseName && links[baseName]?.getWorldPosition) links[baseName].getWorldPosition(basePos);

        let bestName: string | null = null;
        let bestDist = -Infinity;
        for (const name of names) {
          const link = links[name];
          if (!link?.getWorldPosition) continue;
          const p = new THREE.Vector3();
          link.getWorldPosition(p);
          const d = p.distanceTo(basePos);
          if (d > bestDist) {
            bestDist = d;
            bestName = name;
            pos.copy(p);
          }
        }
        if (bestName) return { ok: true as const, pos };
      }

      // Fallback: use robot's bounding box center
      const box = new THREE.Box3().setFromObject(robot);
      if (box.isEmpty()) return { ok: false as const, pos };
      box.getCenter(pos);
      return { ok: true as const, pos };
    };

    const createMeshLoader = (isPhantom: boolean) => (path: string, _mgr: any, done: Function) => {
      const filename = path.split('/').pop() || path;

      const loadGeometry = (url: string) => {
        stlLoader.load(url, (geometry) => {
          const mesh = new THREE.Mesh(geometry, isPhantom ? phantomMaterial : actualMaterial);
          mesh.castShadow = !isPhantom;
          mesh.receiveShadow = !isPhantom;
          mesh.renderOrder = isPhantom ? 2 : 1;
          done(mesh);
        }, undefined, (err) => {
          console.warn(`Failed to load STL: ${url}`, err);
          done(null);
        });
      };

      if (assets[filename]) {
        loadGeometry(assets[filename]);
      } else if (basePath) {
        const cleanBasePath = basePath.replace(/\/$/, '');
        loadGeometry(`${cleanBasePath}/${filename}`);
      } else {
        done(null);
      }
    };

    try {
      urdfLoader.loadMeshCb = createMeshLoader(false);
      const actualRobot = urdfLoader.parse(urdfContent);
      actualRobot.rotation.x = -Math.PI / 2;
      scene.add(actualRobot);
      actualRobotRef.current = actualRobot;

      urdfLoader.loadMeshCb = createMeshLoader(true);
      const phantomRobot = urdfLoader.parse(urdfContent);
      phantomRobot.rotation.x = -Math.PI / 2;
      phantomRobot.visible = false;
      scene.add(phantomRobot);
      phantomRobotRef.current = phantomRobot;

      manager.onLoad = () => {
        // Ensure our materials win over URDF-defined colors/materials after all meshes are loaded.
        applyRobotMaterial(actualRobot, actualMaterial, false);
        applyRobotMaterial(phantomRobot, phantomMaterial, true);

        if (actualRobotRef.current) {
          const box = new THREE.Box3().setFromObject(actualRobotRef.current);
          const center = new THREE.Vector3();
          box.getCenter(center);
          controls.target.copy(center);
          controls.update();
        }
      };
    } catch (err) {
      console.error("URDF Parsing or 3D Scene Setup failed:", err);
    }

    let frameId: number;
    const startTime = Date.now();

    const animate = () => {
      frameId = requestAnimationFrame(animate);
      const time = (Date.now() - startTime) * 0.001;

      if (actualRobotRef.current && phantomRobotRef.current) {
        const isOpt = isOptimizingRef.current;
        phantomRobotRef.current.visible = isOpt;
        tcpPhantom.visible = isOpt;

        const jointNames = Object.keys(actualRobotRef.current.joints);
        jointNames.forEach((name, idx) => {
          const joint = actualRobotRef.current.joints[name];
          const pJoint = phantomRobotRef.current.joints[name];
          if (!joint || !pJoint) return;

          const freq = 0.5 + idx * 0.1;
          const amp = 0.4;
          const q_ref = isOpt ? Math.sin(time * freq) * amp : 0;

          // NOTE: Do NOT inject synthetic tracking lag / vibration into motion.
          // This visualizer is kinematic-only unless fed by a real simulator/state stream.
          const q_act = q_ref;

          if (pJoint.setJointValue) pJoint.setJointValue(q_ref);
          if (joint.setJointValue) joint.setJointValue(q_act);
        });

        // Update TCP marker positions
        const tcpA = computeTcpWorldPosition(actualRobotRef.current);
        if (tcpA.ok) tcpActual.position.copy(tcpA.pos);
        const tcpP = computeTcpWorldPosition(phantomRobotRef.current);
        if (tcpP.ok) tcpPhantom.position.copy(tcpP.pos);
      }

      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!mountRef.current) return;
      const newWidth = mountRef.current.clientWidth;
      const newHeight = mountRef.current.clientHeight;
      camera.aspect = newWidth / newHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(newWidth, newHeight);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(frameId);
      disposeObject(actualRobotRef.current);
      disposeObject(phantomRobotRef.current);
      actualRobotRef.current = null;
      phantomRobotRef.current = null;
      tcpGeo.dispose();
      tcpActualMat.dispose();
      tcpPhantomMat.dispose();
      renderer.dispose();
      mountRef.current?.removeChild(renderer.domElement);
    };
  }, [urdfContent, assets, basePath]);

  return (
    <div className="relative w-full h-full group">
      <div ref={mountRef} className="w-full h-full" />
      <div className="absolute top-4 right-4 flex flex-col gap-2 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-300">
         <div className="bg-zinc-900/80 border border-zinc-800 px-3 py-2 rounded-lg text-[10px] text-zinc-400 space-y-1">
            <div className="flex justify-between gap-4"><span>旋转</span> <span className="text-zinc-500">左键</span></div>
            <div className="flex justify-between gap-4"><span>平移</span> <span className="text-zinc-500">右键</span></div>
            <div className="flex justify-between gap-4"><span>缩放</span> <span className="text-zinc-500">滚轮</span></div>
         </div>
      </div>
      {!urdfContent && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/50 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-zinc-500 font-mono">Initializing 3D Workspace...</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default RobotVisualizer;
